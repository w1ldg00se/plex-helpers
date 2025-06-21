#!/usr/bin/env python3
"""
Description see plexPlaylistDedup.md
"""

import argparse
from collections import defaultdict
from tqdm import tqdm
from plexHelpers import mood_add, mood_del, get_track_quality, plex_connect, select_playlist, select_user

def main():
    """
    Main function

    Note about print(): \r\033[K = jump to line start and flush line
    """
    parser = argparse.ArgumentParser()
    parser.description = "Removes all duplicate songs from a smart playlist"
    parser.add_argument(
        '-m', '--match',
        nargs='+',  # Accept one or more values
        choices=['guid', 'title', 'duration'],
        default=['guid'],
        help="Which attributes to match for duplicate checking: guid, title, duration. Default is guid, but you may use title and duration if you have duplicate tracks over multiple albums."
    )
    parser.add_argument(
        '-p', '--playlist',
        type=str,
        help="Playlist title to remove duplicates from (supports regex, omit for interactive selection)"
    )
    parser.add_argument(
        '-u', '--user',
        nargs='?',           # Optional value
        const=True,          # If --user is passed without a value, set to True
        help='Only for server owner: Username from which to choose the playlist (omit username to select a user from a list)'
    )
    parser.add_argument('-y', '--yes', action='store_true', help="Don't ask for 'Press Y to continue'")
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose mode (prints title of each track)')
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

    # Select a playlist (with --playlists you can choose multiple playlists via regex)
    playlists = select_playlist(plex, 'audio', True, args.playlist, multiple=True)
    if playlists == None:
        return
    if not isinstance(playlists, list):
        playlists = [playlists]

    # remove duplicates from selected playlists
    for playlist in playlists:
        if len(playlists) > 1:
            print(f'\r\033[KPlaylist: {playlist.title}')
        moodName = 'Duplicate ' + playlist.title
        moodNameL = moodName.lower()

        print("\r\033[KLoading section...", end="")
        section = playlist.section()

        print("\r\033[KLoading moods...", end="")
        allMoods = section.listFilterChoices('mood', 'track') # get all moods that can be specified on the track (not an album)
        dupMoods = [m for m in allMoods if m.title.lower().startswith('duplicate ')] # all 'Duplicate *' moods
        mood = next((m for m in dupMoods if m.title.lower() == moodNameL), None)     # mood for this playlist (may not exist at this time)

        print("\r\033[KLoading filter...", end="")
        filters = playlist.filters()['filters']
        # delete all filters with 'track.mood!' containing a id of a 'Duplicate *' mood
        for key in filters:
            if isinstance(filters[key], list):
                for i, f in enumerate(filters[key]):
                    for k, v in f.items():
                        if k == 'track.mood!':
                            for m in dupMoods:
                                if v == m.key:
                                    filters[key].pop(i)
                                    break

        # Run searchTracks with the modified filter so we get all songs that would be in the playlist without any 'Duplicate *' moods filter to
        # - always mark the best quality version of duplicates as unique
        # - in case the oririnal song was deleted another one of the duplicates needs to be choosen as unique
        if mood:
            # Load those with and without the 'Duplicate *' mood separate. This way we know if the mood is
            # set or not set. Depending on that we can keep the currently unique track still be the unique
            # track (except of course one with higher quality appears) and to know if the mood has to be
            # added/removed.
            # On huge playlists this is faster than loading all tracks at once and using the moods
            # property, as the moods get only loaded when accessed and that would result in a request for
            # each track and that is very slow.
            filtersExclMood = {'and': [
                {'track.mood!': mood.key},
                filters
            ]}
            filtersInclMood = {'and': [
                {'track.mood=': mood.key},
                filters
            ]}
            print("\r\033[KLoading duplicate tracks...", end="")
            tracks = section.searchTracks(filters=filtersInclMood) # load currently duplicate tracks
            for track in tracks:
                track.hasMood = True # tracks have the mood set (=currently duplicate tracks)
            print("\r\033[KLoading unique tracks...", end="")
            tracks.extend(section.searchTracks(filters=filtersExclMood)) # load currently unique tracks first
        else:
            # mood is not existing yet, so order doesn't matter and all can be loaded at once
            # that also means there is no 'Duplicate *' mood filter and we can just load the tracks from the playlist which is faster
            print("\r\033[KLoading tracks...", end="")
            tracks = playlist.items()

        print("\r\033[KSearching duplicates...", end="")
        uniqueTracks = []    # List with unique tracks
        duplicateTracks = [] # List with duplicates
        # The playlist may be huge (many thousands of tracks), this is a fast way to check for duplicates:
        # Create a dictionary with the index containing of a string of the track attrs values specified in --mode
        # Each element in the dictionary contains a list of 1..n tracks
        trackDup = defaultdict(list)
        for track in tracks:
            dupGuid = ''
            for attr in args.match:
                dupGuid = dupGuid + str(getattr(track, attr, '')).replace(' ', '').lower()
            trackDup[dupGuid].append(track)

        # Now just split it in 2 lists, one for unique and one for duplicate tracks,
        # When there are duplicates the one with the best quality is choosen to be the unique one.
        for trackList in trackDup.values():
            if len(trackList) > 1:
                # Sort tracks by codec, then bitrate, then sample rate
                trackList.sort(key=get_track_quality, reverse=True)
                uniqueTracks.extend(trackList[:1])     # Mark best quality as unique
                duplicateTracks.extend(trackList[1:])  # Mark others as duplicates
            else:
                uniqueTracks.extend(trackList[:1])     # Mark best quality as unique

        print(f"\r\033[KFound {len(tracks)} tracks: {len(uniqueTracks)} unique and {len(duplicateTracks)} duplicates.")

        if args.verbose:
            print("\nUnique tracks:")
            for track in uniqueTracks:
                print(f'{track.title} - {track.parentTitle} - {track.grandparentTitle} - {track.guid}')

            print("\nDuplicate tracks:")
            for track in duplicateTracks:
                print(f'{track.title} - {track.parentTitle} - {track.grandparentTitle} - {track.guid}')

        # Ask for user confirmation before applying mood to all tracks
        if not args.yes:
            choice = input("Press Y to continue: ").strip().lower()
            if choice != 'y':
                print("Aborted.")
                exit(1)

        print(f"Applying mood '{moodName}' to duplicates...")
        # Note: applying moods in parallel didn't improve speed, this just takes some time
        with tqdm(total=len(tracks)) as pbar:
            for track in uniqueTracks:
                if getattr(track, "hasMood", False): # only delete mood from tracks that have the mood set
                    mood_del(track, moodName) # delete mood, in case tracks have it set so they are not filtered any more
                    pbar.update(1)
                    pbar.refresh()
                else: # mood already set, nothing to do
                    pbar.update(1)

            for track in duplicateTracks:
                if not getattr(track, "hasMood", False): # only add mood to tracks that haven't the mood set
                    mood_add(track, moodName) # add mood, so tracks can be filtered
                    pbar.update(1)
                    pbar.refresh()
                else: # mood already set, nothing to do
                    pbar.update(1)

        if not mood:
            print(f"Updating smart playlist filter to exclude tracks with mood '{moodName}'...")

            allMoods = section.listFilterChoices('mood', 'track') # get all moods that can be specified on the track (not an album)
            mood = next((m for m in allMoods if m.title.lower() == moodNameL), None)     # mood for this playlist (may not exist at this time)

            # add filter to exclude mood
            k,v = next(iter(filters.items()))
            if k == 'and': # 'and' filter: add mood filter as first element
                filters['and'].insert(0, {'track.mood!': mood.key})
            else: # 'or' filter, add 'and' node with the mood filter before the original filter
                filters = {'and': [
                    {'track.mood!': mood.key},
                    {k: v}
                ]}
            playlist.updateFilters(filters=filters)

    print("\r\033[KFinished")


if __name__ == '__main__':
    main()