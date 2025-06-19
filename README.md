# plex-helpers

Helper scripts for Plex Media Server:
- [Plex Smart Playlist Deduplicator](plexPlaylistDedup.md): Removes all duplicate songs from a smart playlist.
- [Plex Delete Media](plexDeleteMedia.py): Deletes all items found in the selected playlist to reclaim storage space.
- [Plex Download Media](plexDownloadMedia.py): Downloads all items found in the selected playlist to the local computer.
- [Plex Docker Update](plexDockerUpdate.py): Restart plex's docker container when a plex update available.

## Requirements
- [Python 3](https://www.python.org/) (Tested with 3.13)
- [PlexAPI](https://pypi.org/project/PlexAPI/) (Tested with 4.17.0)
- [tqdm](https://pypi.org/project/tqdm/) (Tested with 4.67.1)

## Installation
Clone this repository, then set up the virtual environment:
```sh
# create the venv
python3 -m venv .venv
# activate the venv
source .venv/bin/activate  # for Linux
.venv\Scripts\activate     # for Windows (may need "Set-ExecutionPolicy RemoteSigned -Scope CurrentUser" to work)
# install all requirements
pip install --upgrade -r requirements.txt
# Now you can run any of the helper scripts listed above via `python plex...py`
```
On the first run of any helper script it asks for your plex credentials (2FA supported) and saves them in `.settings.json`, after that it automatically uses the saved credentials.
When you already know your plex token, you can manually create a file `.settings.json` with the following content:
```json
{
    "baseurl": "http://your-plex-server:32400",
    "token": "your-plex-token"
}
```