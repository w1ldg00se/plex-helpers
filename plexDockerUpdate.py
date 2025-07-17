#!/usr/bin/env python3
"""
Restart plex's docker container when a plex update available, but only when nobody is streaming currently.
"""

from plexHelpers import plex_connect
import docker
import requests


def is_latest(plex):
    """
    Returns True if the installed version of Plex Media Server is the latest.

    Like isLatest from plexapi but that seems to always return true, but it works when '?X-Plex-Product=Plex%20Web' is specified.
    """
    headers = {'Accept': 'application/json', 'X-Plex-Token': plex._token}
    url = f'{plex._baseurl}/updater/status?X-Plex-Product=Plex%20Web'
    response = requests.get(url, headers=headers)
    try:
        return response.ok and response.json()['MediaContainer']['size'] == 0
    except:
        return True


def main():
    plex = plex_connect()
    isLatest = plex.isLatest() and is_latest(plex)
    sessions = plex.sessions()

    if isLatest:
        print("\r\033[KAlready up-to-date")

    if sessions:
        print("\r\033[KSomebody's playing")

    if not isLatest and not sessions:
        client = docker.from_env()
        container = client.containers.get('plex')
        container.restart()

if __name__ == '__main__':
    main()
