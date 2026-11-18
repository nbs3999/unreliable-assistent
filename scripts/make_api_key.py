"""Issue an API key bound to one tenant and user (gaps.md § 1.1).

The raw key is printed once and never stored. The keys file gets only its SHA-256 digest.

Usage:
  python scripts/make_api_key.py --keys-file /etc/assistant/api_keys.json \
      --tenant tenant_acme --user user_1 --roles user
  python scripts/make_api_key.py --keys-file /etc/assistant/api_keys.json \
      --tenant tenant_acme --user user_reviewer_1 --roles reviewer

Give the keys file to the service with API_KEYS_FILE=/etc/assistant/api_keys.json.
Keep the keys file out of git (it is listed in .gitignore).
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assistant.api.auth import ROLE_REVIEWER, ROLE_USER, digest_of  # noqa: E402

TENANT_RE = re.compile(r"^tenant_[a-z0-9_-]{1,56}$")
USER_RE = re.compile(r"^user_[a-z0-9_-]{1,64}$")
VALID_ROLES = {ROLE_USER, ROLE_REVIEWER}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys-file", type=Path, required=True)
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--user", required=True)
    ap.add_argument("--roles", default=ROLE_USER, help="comma list from: user, reviewer")
    args = ap.parse_args()

    roles = [r.strip() for r in args.roles.split(",") if r.strip()]
    if not TENANT_RE.match(args.tenant):
        ap.error("tenant must match ^tenant_[a-z0-9_-]{1,56}$")
    if not USER_RE.match(args.user):
        ap.error("user must match ^user_[a-z0-9_-]{1,64}$")
    if not roles or not set(roles) <= VALID_ROLES:
        ap.error(f"roles must be a non-empty subset of {sorted(VALID_ROLES)}")

    token = secrets.token_urlsafe(32)
    entries = json.loads(args.keys_file.read_text(encoding="utf-8")) if args.keys_file.exists() else []
    entries.append({"key_sha256": digest_of(token), "tenant_id": args.tenant,
                    "user_id": args.user, "roles": roles})
    args.keys_file.parent.mkdir(parents=True, exist_ok=True)
    args.keys_file.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    try:
        args.keys_file.chmod(0o600)
    except OSError:
        pass

    print(f"Issued key for {args.tenant}/{args.user} roles={roles}")
    print(f"API key (shown once, store it now): {token}")


if __name__ == "__main__":
    main()
