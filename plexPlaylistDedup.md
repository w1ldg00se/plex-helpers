# Plex Smart Playlist Deduplicator
Removes all duplicate songs from a smart playlist.
It is using the workaround with setting a mood on duplicate songs, and then excluding those songs from the smart playlist.

Many thanks to [dfatih/PlexMusicDeDuplicator](https://github.com/dfatih/PlexMusicDeDuplicator) and [jonasbp2011/PlexSmartPlaylistDeduplicator](https://github.com/jonasbp2011/PlexSmartPlaylistDeduplicator) from which this scipt originates.

## How it works
The script works by choosing the name of the smart playlist you wish to remove duplicate songs from. It adds the mood `Duplicate title-of-playlist` to any of the songs found as duplicates. Just a general `Duplicate` mood doesn't work because a track could be in multiple playlists and be only a duplicate in one specific playlist and not in other playlists, thats why the name of the playlist is included in the mood.
Out of all the duplicate tracks one version with the best quality is choosen as the unique track, and unless a better quality version appears this one stays the unique one, even after multiple runa of this script. This is relevent for playlists synced for offline play with Plexamp so it doesn't have to sync another version of the same song after each time this script is run.
The smart playlist filter is automatically updated to include the filter `Track Mood` `is not` `Duplicate title-of-playlist` to exclude duplicate tracks.
In case a smart playlist was renamed the `Duplicate` mood for the old name will be automatically removed.
You can run the script as often as you like, even as a cronjob when you specify at least the `--playlist` and `--yes` command-line parameters.

## How to run
After [installation](README.md#installation), just run the script:
```sh
# activate the venv
source .venv/bin/activate  # for Linux
.venv\Scripts\activate     # for Windows (may need "Set-ExecutionPolicy RemoteSigned -Scope CurrentUser" to work)

python plexPlaylistDedup.py

# By default duplicates are matched via guid, but if you have duplicate tracks over multiple albums (different guids) you may want to match duplicates via title and duration
python plexPlaylistDedup.py --match title duration

#Further commandline options:
--playlist title-of-playlist # Playlist title to remove duplicates from (supports regex, omit for interactive selection)
--user username # Only for server owner: Username from which to choose the playlist (omit username to select a user from a list)
--yes     # Don't ask for 'Press Y to continue'
--verbose # Verbose mode (prints title of each track)
--help:   # Show help
```
It shows a list of all your playlists and you have to input the number or title of the playlist. It shows how many duplicates are found and asks you to confirm that you want to continue, then it marks the duplicate tracks and updates the smart playlist filter.