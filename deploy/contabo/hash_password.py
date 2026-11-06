#!/usr/bin/env python3
"""Create the PBKDF2 password hash used by the single-operator sign-in."""

import argparse
import getpass
import hashlib
import secrets
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdin", action="store_true", help="read a password from standard input")
    args = parser.parse_args()
    password = sys.stdin.readline().rstrip("\r\n") if args.stdin else getpass.getpass("New OpsPilot password: ")
    if len(password) < 16:
        parser.error("password must contain at least 16 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310000).hex()
    print(f"pbkdf2_sha256$310000${salt.hex()}${digest}")


if __name__ == "__main__":
    main()
