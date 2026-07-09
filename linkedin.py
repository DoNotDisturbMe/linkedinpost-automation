"""
LinkedIn Post Automation (Official API)
----------------------------------------
Usage:
  1. Set env vars: LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET, LINKEDIN_REDIRECT_URI
  2. Run: python linkedin_post.py --auth        (one-time, opens browser, gets token)
  3. Run: python linkedin_post.py --post "Your post text here"

Requires: pip install requests
"""

import os
import sys
import json
import webbrowser
import requests
from urllib.parse import urlencode, parse_qs, urlparse
from http.server import HTTPServer, BaseHTTPRequestHandler

CLIENT_ID = os.environ.get("LINKEDIN_CLIENT_ID")
CLIENT_SECRET = os.environ.get("LINKEDIN_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("LINKEDIN_REDIRECT_URI", "http://localhost:8000/callback")
TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".linkedin_token.json")
SCOPE = "w_member_social openid profile"

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
POSTS_URL = "https://api.linkedin.com/rest/posts"
LINKEDIN_VERSION = "202506"  # LinkedIn API version header (YYYYMM, must be within last 12 months)


class CallbackHandler(BaseHTTPRequestHandler):
    """Captures the ?code= param from LinkedIn's redirect."""
    auth_code = None

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        if "code" in query:
            CallbackHandler.auth_code = query["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Login successful. You can close this tab.")
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # silence server logs


def run_auth_flow():
    if not CLIENT_ID or not CLIENT_SECRET:
        sys.exit("Set LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET env vars first.")

    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
    }
    url = f"{AUTH_URL}?{urlencode(params)}"
    print(f"Opening browser for LinkedIn login:\n{url}\n")
    webbrowser.open(url)

    server = HTTPServer(("localhost", 8000), CallbackHandler)
    print("Waiting for LinkedIn redirect on http://localhost:8000/callback ...")
    while CallbackHandler.auth_code is None:
        server.handle_request()

    code = CallbackHandler.auth_code
    token_resp = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    })
    token_resp.raise_for_status()
    token_data = token_resp.json()

    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f)

    print(f"Token saved to {TOKEN_FILE}. Expires in {token_data.get('expires_in')} seconds.")


def get_access_token():
    env_token_json = os.environ.get("LINKEDIN_TOKEN_JSON")
    if env_token_json:
        return json.loads(env_token_json)["access_token"]
    if not os.path.exists(TOKEN_FILE):
        sys.exit("No token found. Run with --auth first, or set LINKEDIN_TOKEN_JSON env var.")
    with open(TOKEN_FILE) as f:
        return json.load(f)["access_token"]


def get_person_urn(access_token):
    resp = requests.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
    resp.raise_for_status()
    sub = resp.json()["sub"]
    return f"urn:li:person:{sub}"


def escape_commentary(text):
    """LinkedIn's Posts API commentary field treats (, ), [, ], {, }, <, >, |, *, _, ~, \\
    as reserved characters for its annotation syntax. Unescaped, they can truncate
    or break parsing of the rest of the post. # and @ are left alone since those
    power hashtags/mentions and work fine as plain text."""
    reserved = ['\\', '(', ')', '[', ']', '{', '}', '<', '>', '|', '*', '_', '~']
    result = text.replace('\\', '\\\\')  # escape backslash first
    for ch in reserved:
        if ch == '\\':
            continue
        result = result.replace(ch, '\\' + ch)
    return result


def add_comment(post_urn, text):
    """post_urn example: urn:li:share:7481060825974104065"""
    access_token = get_access_token()
    author_urn = get_person_urn(access_token)

    encoded_urn = requests.utils.quote(post_urn, safe="")
    url = f"https://api.linkedin.com/rest/socialActions/{encoded_urn}/comments"

    payload = {
        "actor": author_urn,
        "message": {"text": text},
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "LinkedIn-Version": LINKEDIN_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }

    resp = requests.post(url, headers=headers, data=json.dumps(payload))
    if resp.status_code in (200, 201):
        print("Comment added. ID:", resp.headers.get("x-restli-id", "(no id returned)"))
    else:
        print("Failed:", resp.status_code, resp.text)


def create_post(text):
    access_token = get_access_token()
    author_urn = get_person_urn(access_token)

    payload = {
        "author": author_urn,
        "commentary": escape_commentary(text),
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": []
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "LinkedIn-Version": LINKEDIN_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }

    resp = requests.post(POSTS_URL, headers=headers, data=json.dumps(payload))
    if resp.status_code == 201:
        post_urn = resp.headers.get("x-restli-id")
        print("Post published. ID:", post_urn)
        return post_urn
    else:
        print("Failed:", resp.status_code, resp.text)
        return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:\n  python linkedin_post.py --auth\n  python linkedin_post.py --post \"text\"")
        sys.exit(1)

    if sys.argv[1] == "--auth":
        run_auth_flow()
    elif sys.argv[1] == "--post":
        if len(sys.argv) < 3:
            sys.exit("Provide post text: --post \"your text\"")
        create_post(sys.argv[2])
    elif sys.argv[1] == "--post-file":
        if len(sys.argv) < 3:
            sys.exit("Provide file path: --post-file post.txt")
        with open(sys.argv[2], "r", encoding="utf-8") as f:
            create_post(f.read())
    elif sys.argv[1] == "--comment":
        if len(sys.argv) < 4:
            sys.exit("Usage: --comment <post_urn> \"comment text\"")
        add_comment(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "--comment-file":
        if len(sys.argv) < 4:
            sys.exit("Usage: --comment-file <post_urn> comment.txt")
        with open(sys.argv[3], "r", encoding="utf-8") as f:
            add_comment(sys.argv[2], f.read())
    else:
        print("Unknown argument.")
