#!/usr/bin/env python3
"""
Restart plex's docker container when a plex update available, but only when nobody is streaming currently.
"""

from plexHelpers import plex_connect
import docker

def main():
    plex = plex_connect()
    isLatest = plex.isLatest()
    sessions = plex.sessions()

    if isLatest:
        print("Already up-to-date")

    if sessions:
        print("Somebody's playing")

    if not isLatest and not sessions:
        client = docker.from_env()
        container = client.containers.get('plex')
        container.restart()

if __name__ == '__main__':
    main()
