#!/usr/bin/env python3
"""
Deletes all items found in a playlist from the server to reclaim storage space.
It shows a list of items that will get deleted and asks 2 times if you really want to delete those.

You can run script interactively or specify everything with these command-line arguments:
--playlist playlistname: Playlist that contains items to be deleted
--user username: Only for server owner: Username from which to choose the playlist (omit username to select a user from a list)
--yes: Don't ask for 'Press Y to continue' (items will get DELETED from the server without questions)
--help: Show help
"""

import argparse
import sys
from plexHelpers import plex_connect, select_user, select_playlist, get_file_size, size_str


def main():
    parser = argparse.ArgumentParser()
    parser.description = "Deletes all items found in a playlist from the server to reclaim storage space"
    parser.add_argument(
        '-p', '--playlist',
        type=str,
        help="Playlist that contains items to be deleted"
    )
    parser.add_argument(
        '-u', '--user',
        nargs='?',           # Optional value
        const=True,          # If --user is passed without a value, set to True
        help='Only for server owner: Username from which to choose the playlist (omit username to select a user from a list)'
    )
    parser.add_argument('-y', '--yes', action='store_true', help="Don't ask for 'Press Y to continue' (items will get DELETED from the server without questions)")
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

    print('\r\033[KItems to delete:')
    filessize = 0
    for item in playlist.items():
        filesize = get_file_size(item)
        filessize += filesize
        print(f"{item.title} ({size_str(filesize)})")

        # show some warnings (i usually only delete things i haven't rated or completely viewed)
        if item.userRating:
            print(f"WARNING: Rating of {item.userRating/2} stars")

        if item.viewCount:
            print(f"WARNING: Was viewed {item.viewCount} times")

    print(f"Total: {len(playlist.items())} items, {size_str(filessize)}")
    print("-------------------------------------------------------------")

    # double security check before deleting
    if not args.yes:
        choice = input("Press Y to continue deleting these items: ").strip().lower()
        if choice != 'y':
            print("Aborted.")
            sys.exit(1)

        choice = input('Type YES if you REALLY WANT TO DELETE these items: ').strip()
        if choice != 'YES':
            print("Aborted.")
            sys.exit(1)

    # delete items
    print("Deleting...", end="", flush=True)
    for item in playlist.items():
        item.delete()

    print("\r\033[KFinished")


if __name__ == '__main__':
    main()