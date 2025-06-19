#!/usr/bin/env python3
"""
Downloads all items from a playlist to a local destination.
Depending on the type of media a directory for Movies/TV-Shows/Music, etc will be created (depending on the name in plex)
and all items will be downloaded into it.

Already locally existing media won't get downloaded again, downloads of partially downloaded media will be resumed.
Before downloading it shows a list (and it's filesize) of locally missing media that will be downloaded.

You can run script interactively or specify everything with these command-line arguments:
--playlist playlistname: Playlist that contains items to be downloaded
--user username: Only for server owner: Username from which to choose the playlist (omit username to select a user from a list)
--destination path: Destination path for downloaded items (without it you can interactively choose removeable/mounted destinations)
--yes: Don't ask for 'Press Y to continue' (items will get downloaded without questions)
--help: Show help
"""

import argparse
import sys
from plexHelpers import download_item, plex_connect, select_destination, select_playlist, select_user, size_str


def main():
    parser = argparse.ArgumentParser()
    parser.description = "Downloads all items from a playlist to a local destination"
    parser.add_argument(
        '-p', '--playlist',
        type=str,
        help="Playlist that contains items to be downloaded"
    )
    parser.add_argument(
        '-u', '--user',
        nargs='?',           # Optional value
        const=True,          # If --user is passed without a value, set to True
        help='Only for server owner: Username from which to choose the playlist (omit username to select a user from a list)'
    )
    parser.add_argument(
        '-d', '--destination',
        type=str,
        help="Destination path for downloaded items (without it you can interactively choose removeable/mounted destinations)"
    )
    parser.add_argument('-y', '--yes', action='store_true', help="Don't ask for 'Press Y to continue' (items will get downloaded without questions)")
    args = parser.parse_args()

    # Connect to plex
    plex = plex_connect()

    # Select a user
    if args.user is True:
        plex = select_user(plex)
    elif args.user:
        plex = select_user(plex, choice=args.user)
    if not plex:
        return

    # Select a playlist
    playlist = select_playlist(plex, choice=args.playlist)
    if not playlist:
        return

    destination = args.destination
    if not destination:
        destination = select_destination(['Downloads'])

    print('\r\033[KItems to download:')
    itemCount = 0
    filessize = 0
    for item in playlist.items():
        filesize = download_item(plex, item, True, destination) # returns how many bytes would be downloaded
        if filesize > 0:
            itemCount += 1
            filessize += filesize
            print(f"{item.title} ({size_str(filesize)})")
        # else: file already exists locally

    print(f"Total: {itemCount} items, {size_str(filessize)}")
    print("-------------------------------------------------------------")

    if not args.yes:
        choice = input("Press Y to continue downloading: ").strip().lower()
        if choice != 'y':
            print("Aborted.")
            sys.exit(1)

    # download items
    for i, item in enumerate(playlist.items(), start=1):
        download_item(plex, item, False, destination, f"[{i}/{itemCount}] {item.title[:20]}")

    print("Finished")


if __name__ == '__main__':
    main()