#!/usr/bin/env python3
"""
Places each item of a section in a collection. The collection name is the top subfolder of the file location.
Items not in a subfolder are added to collection 'Others'.

i.e. Pictures/Album1/**.jpg -> all those pictures will be added to collection 'Album1'.
Should work with every section type, but only makes sense if you organized your media in the section that way.
"""

import argparse
import os
from pathlib import PurePath
from plexapi.collection import Collection
from tqdm import tqdm
from plexHelpers import plex_connect, select_section

def main():
    """
    Main function

    Note about print(): \r\033[K = jump to line start and flush line
    """
    parser = argparse.ArgumentParser()
    parser.description = "Places each item in a collection with the name of the top subfolder it is in"
    parser.add_argument(
        '-s', '--section',
        type=str,
        help="Title of section"
    )
    parser.add_argument('-y', '--yes', action='store_true', help="Don't ask for 'Press Y to continue'")
    args = parser.parse_args()

    # Connect to plex
    plex = plex_connect()

    # Select a section
    section = select_section(plex, None, args.section)
    if section == None:
        return

    # Ask for user confirmation before applying mood to all tracks
    if not args.yes:
        choice = input("Press Y to continue: ").strip().lower()
        if choice != 'y':
            print("Aborted.")
            exit(1)

    print(f'\r\033[KUpdating collections in {section.title}...')
    collections = {}
    locations = [os.path.normpath(l) for l in section.locations]

    for item in tqdm(section.all()):
        path = os.path.dirname(os.path.normpath(item.locations[0]))
        name = 'Others' # default collection name for files not in a subdirectory
        for location in locations:
            try:
                name = PurePath(path).relative_to(location).parts[0]
                break
            except:
                pass

        try:
            if name in collections:
                collection = collections[name]
            else:
                collection = section.collection(name)
                collections[name] = collection

            if not item in collection.items():
                collection.addItems([item])
        except:
            collection = Collection.create(plex, name, section, [item])
            collections[name] = collection

    print("\r\033[KFinished")


if __name__ == '__main__':
    main()