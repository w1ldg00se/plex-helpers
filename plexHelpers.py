#!/usr/bin/env python3
"""
Various helper functions for plex.

Note about print(): \r\033[K = jump to line start and flush line
"""

import datetime
import getpass
import json
import math
import os
import pathlib
import platform
import re
import requests
import signal
import stat
import shutil
import sys
from tqdm import tqdm
from typing import Optional, Literal
from plexapi.myplex import MyPlexAccount
from plexapi.server import PlexServer


def clean_path_part(pathPart):
    """
    Remove illegal characters that are forbidden in path parts on Windows.
    Note: do not specify a full path containing path separators, those will get removed.
    """
    # this are all characters forbidden on the windows NTFS filesystem
    forbidden_characters = r'<>/\\:"|?*'

    for x in forbidden_characters:
        pathPart = pathPart.replace(x, ' ')
    while '  ' in pathPart:
        pathPart = pathPart.replace('  ', ' ')
    return pathPart


def download_item(plex, item, skipDownload = False, basepath: Optional[str] = 'Downloads', description: Optional[str] = 'Downloading'):
    """
    Downloads all media parts of the specified item into the basepath directory.
    Existing files with correct filesize are skipped, otherwise the download is resumed.

    When skipDownload = True then no files are downloaded, the function just returns how many bytes would be downloaded.

    Note: plexapi provides item.download() but that doesn't provide a progress bar
    so this function downloads the files manually to be able to show a progress.
    """
    chunk_size = 64*1024  # 64 Kibibyte

    def compare_partial_file(plex, part, file):
        """
        Downloads the first 1MB and compares it with the local file.
        plexapi doesn't show when the file was last modified (only the metadata).
        So whenever the filesizes from the local and remote file differ there is no other
        option than to download the first part and compare it to tell if the file needs to
        be completely re-downloaded (file on server changed) or the download can be resumed.
        """
        byte_limit = min(1024*1024, os.path.getsize(file)) # 1MB or filesize when file is smaller
        headers = {'Range': f'bytes=0-{byte_limit - 1}'}
        response = requests.get(get_url(plex, part.key), headers=headers, stream=True)

        with open(file, 'rb') as local_file:
            total = 0
            for remote_chunk in response.iter_content(chunk_size):
                local_chunk = local_file.read(len(remote_chunk))
                if remote_chunk != local_chunk:
                    return False  # Files differ
                total += len(remote_chunk)
                if total >= byte_limit:
                    break

        return True  # First 1MB are the same


    total_download_size = 0
    section = item.section()
    for media_ix, media in enumerate(item.media):
        for part_ix, part in enumerate(media.parts):
            total_download_size += part.size
            existing_filesize = 0
            file = os.path.join(basepath, section.title, unique_path(section, item, media_ix, part_ix))
            if os.path.exists(file):
                existing_filesize = os.path.getsize(file)
                if part.size == existing_filesize:
                    total_download_size -= existing_filesize
                    continue # file already exists
                else:
                    if compare_partial_file(plex, part, file): # file exists partially, resume downloading
                        total_download_size -= existing_filesize
                    else: # file was updated on the server, needs to be downloaded again
                        existing_filesize = 0
                        if not skipDownload: os.remove(file)
            if skipDownload:
                continue

            # create local directory for download
            path = os.path.dirname(file)
            if not os.path.isdir(path):
                os.makedirs(path)

            # download with progress bar, resume existing files
            headers = None
            if existing_filesize > 0:
                headers = {"Range": f"bytes={existing_filesize}-"}
            response = requests.get(get_url(plex, part.key), headers=headers, stream=True)


            mode = 'ab' if existing_filesize > 0 else 'wb'
            with open(file, mode) as f, tqdm(
                desc=description,
                total=part.size,
                initial=existing_filesize,
                unit='iB',
                unit_scale=True,
                unit_divisor=1024,
            ) as bar:
                for data in response.iter_content(chunk_size):
                    f.write(data)
                    bar.update(len(data))

    return total_download_size


def get_file_size(item):
    filesize = 0
    for media in item.media:
        for part in media.parts:
            filesize += part.size
    return filesize

class MyFilterChoice:
    """
    Minimal version of plexapi.library.FilterChoice
    """
    def __init__(self, key, title):
        self.key = key
        self.title = title

    def __repr__(self):
        return f"<MyFilterChoice:{self.key}:{self.title}>"

def get_moods_via_autocomplete(plex, section, query):
    """
    Loads a list of moods, starting with query, using the autocomplete feature that is used in the plex web UI.

    You can also run section.listFilterChoices('mood', 'track'), but that is much slower and loads all moods without filtering.
    This returns a list of MyFilterChoice objects, so it's a faster drop-in replacement for listFilterChoices.
    """
    url = get_url(plex, f'/library/sections/{section.key}/autocomplete?type=10&mood.query={query}')
    headers = {'Accept': 'application/json'}
    response = requests.get(url, headers=headers)
    moods = []
    media_container = response.json()['MediaContainer']
    if 'Directory' in media_container:
        for m in media_container['Directory']:
            # Translate the json response to a MyFilterChoice object ('id'->key, 'tag'->title)
            # to be a drop-in replacement for listFilterChoices.
            moods.append(MyFilterChoice(key=m['id'], title=m['tag']))
    return moods


# Quality ranking for audio codecs, used in get_track_quality()
codec_quality = {          # Sorted by quality, compatibility, open-source preferred
    'flac':            13, # lossless, open-source
    'alac':            12, # lossless, Apple's flac version, still open source like flac but less compatibility than flac
    'pcm':             11, # lossless, without compression, so same quality than flac/alac but with worse storage efficiency
    'ape':             10, # lossless, better compression than flac (using more cpu), but proprietary with less compatibility
    'dsd_lsbf_planar':  9, # lossless, has a more analog-style warmth than the accurate flac
    'opus':             8, # lossy, successor of vorbis, free
    'vorbis':           7, # lossy, in lower bitrates aac is better, in higher ones vorbis is better, is free so prefer it over aac
    'aac':              6, # lossy, usully mentioned as successor of mp3, up to 48 channels, requires license
    'ac3':              5, # lossy, up to 5.1 surround sound
    'mp3':              4, # lossy, good compatibility, usually stereo, good for music
    'wmav2':            3, # lossy, can be better than mp3 at lower bitrates, but limited compatibility
    'mp2':              2, # lossy, better for streaming (latency, robustness) than mp3, but mp3 is better for storage efficiency
    'cook':             1  # obsolete RealPlayer format
}

def get_track_quality(track):
    """
    Return a tuple representing the track's quality for comparison in this order:
      - codec
      - bitrate
      - sample rate
      - not having the 'Duplicate *' mood set (via externally set 'hasMood' option, those are currently unique tracks which get higher priority to stay the unique tracks)
    """
    media = track.media[0]

    # Safely access attributes with default values if they don't exist
    codec = getattr(media, 'audioCodec', None) # can be present with value None!
    if not codec:
        try: # try to parse codec from filename
            codec = pathlib.PurePath(media.parts[0].file).suffix[1:].lower()
        except:
            pass
    if codec: # translate codec to a quality rank
        codec_rank = codec_quality.get(codec.lower(), 0)
        if codec_rank == 0:
            raise Exception(f'Please add audio format {codec} to codec_quality')
    else:
        codec_rank = 0 # cannot parse codec at all, use lowest ranking
    bitrate = getattr(media, 'bitrate', 0)
    sample_rate = getattr(media, 'audioSampleRate', 0)
    notHasMood = int(not getattr(track, "hasMood", False))

    return (codec_rank, bitrate, sample_rate, notHasMood)


def get_url(plex, urlpart):
    """
    Generate URL to query the Plex server (for code that can't use plexaapi).

    urlpart: part of the url after the hostname and port, must begin with '/' and can contain '?option=value' arguments.
    """
    return f'{plex._baseurl}{urlpart}&X-Plex-Token={plex._token}'


def mood_add(track, moodName):
    """
    Adds a mood to the track.
    Note: Moods are lazy-loaded, so the first access needs a request to the server.
    """
    if track.moods:
        if any(mood.tag.lower() == moodName.lower() for mood in track.moods):
            return # mood already existing, nothing to do
        track.addMood(moodName)
    else:
        track.addMood(moodName)


def mood_del(track, moodName):
    """
    Deletes a mood from the track.
    Note: Moods are lazy-loaded, so the first access needs a request to the server.
    """
    if track.moods:
        if any(mood.tag.lower() == moodName.lower() for mood in track.moods):
            track.removeMood(moodName)


def plex_connect():
    """
    Connect to the plex server.
    Uses url and token from the file .settings.json, or asks for login credentials and writes .settings.json.
    """
    settings_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.settings.json')
    if os.path.exists(settings_file):
        try:
            # Load connection settings
            with open(settings_file, 'r') as f:
                settings = json.load(f)

            # Authenticate with Plex
            print("Connecting to server...", end="", flush=True)
            return PlexServer(settings['baseurl'], settings['token'])
        except Exception as e:
            os.unlink(settings_file)
            return plex_connect() # connection failed, retry with username and password
    else:
        # Authenticate with username and password
        username = input("Plex username: ")
        pw = getpass.getpass("Plex password: ")
        code = getpass.getpass("2FA token (leave empty if you don't use 2FA): ")

        account = MyPlexAccount(username=username, password=pw, code=code)

        # Choose Server
        serverResoutce = select_server(account)

        # Connect to the server (this can take some time as it probes all connections)
        print("Connecting to server (this can take some time)...", end="", flush=True)
        plex = serverResoutce.connect()

        # Write url and token to settings.json to be reused on further runs
        settings = {
            "baseurl": plex._baseurl,
            "token": plex._token,
        }
        with open(settings_file, 'w') as f:
            json.dump(settings, f, indent=4)
        os.chmod(settings_file, stat.S_IRUSR | stat.S_IWUSR)  # read & write permissions for owner only, equivalent to 0o600

        return plex


def select_destination(paths = []):
    """
    The user can select a specific destination (for downloading files into).
    Specific paths can be specified, and all removeable/mounted media is listed.
    """

    def get_removeable_disks_windows():
        """
        Returns removeable media and network shares on Windows
        """
        import ctypes
        import string

        disks = []
        drive_bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26):
            if drive_bitmask & (1 << i):
                drive_letter = f"{string.ascii_uppercase[i]}:\\"
                drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_letter)
                if drive_type == 2:  # DRIVE_REMOVABLE
                    try:
                        label_buf = ctypes.create_unicode_buffer(1024)
                        fs_buf = ctypes.create_unicode_buffer(1024)
                        ctypes.windll.kernel32.GetVolumeInformationW(
                            ctypes.c_wchar_p(drive_letter),
                            label_buf,
                            len(label_buf),
                            None, None, None,
                            fs_buf,
                            len(fs_buf)
                        )
                        label = label_buf.value or "No Label"
                    except Exception:
                        label = "Unknown"
                    try:
                        total, _, free = shutil.disk_usage(drive_letter)
                        disks.append({
                            'path': drive_letter,
                            'label': label,
                            'total': total,
                            'free': free
                        })
                    except:
                        pass
        return disks


    def get_removeable_disks_linux():
        disks = []
        mount_paths = []
        media_dirs = ['/media', '/run/media', '/mnt']
        for media_dir in media_dirs:
            if os.path.isdir(media_dir):
                for root, dirs, _ in os.walk(media_dir):
                    for name in dirs:
                        mount_path = os.path.join(root, name)
                        if not os.path.ismount(mount_path):
                            for root, dirs, _ in os.walk(mount_path):
                                for name in dirs:
                                    mount_path = os.path.join(root, name)
                                    if os.path.ismount(mount_path):
                                        mount_paths.append(mount_path)
                                break  # avoid recursive scan
                        else:
                            mount_paths.append(mount_path)
                    break  # avoid recursive scan

        for mount_path in mount_paths:
            try:
                total, _, free = shutil.disk_usage(mount_path)
                disks.append({
                    'path': mount_path,
                    'label': os.path.basename(mount_path),
                    'total': total,
                    'free': free
                })
            except:
                pass
        return disks


    destinations = []
    for path in paths:
        if not os.path.exists(path) or os.path.isdir(path):
            destinations.append({
                'path': os.path.abspath(path),
                'label': None,
                'total': None,
                'free': None
            })

    system = platform.system()
    if system == "Windows":
        destinations.extend(get_removeable_disks_windows())
    elif system == "Linux":
        destinations.extend(get_removeable_disks_linux())

    print('\r\033[KChoose Destination:')
    for i,d in enumerate(destinations):
        print(f"{i}: {d['path']}", end="")
        if d["label"]:
            print(f", Label: {d['label']}", end="")
        if d["total"] and d["free"]:
            print(f", Total: {size_str(d['total'])}, Free: {size_str(d['free'])}", end="")
        print()

    destination = None
    choice = input('Destination: ')
    try:
        destination = destinations[int(choice)]
    except (ValueError, IndexError):
        try:
            destination = next((d for d in destinations if d["path"].lower() == choice.lower()), None)
            if not destination:
                destination = next((d for d in destinations if d["label"] and d["label"].lower() == choice.lower()), None)
        except:
            pass

    if destination == None:
        return select_destination(paths)
    return destination['path']


def select_playlist(plex, playlistType: Optional[Literal['audio', 'video', 'photo']] = None, smart: Optional[bool] = None, choice: Optional[str] = None, multiple: Optional[bool] = False):
    """
    Allows the user to choose a playlist.

    Optionally specify a playlist type of audio, video or photo.
    Optionally specify smart as True/False to only get smart/non-smart playlists.
    Optionally specify a playlist name via choice.
    Optionally allows to select multiple playlists, but only when choice is a regex
    """
    playlists = plex.playlists()
    if playlistType:
        playlists = [p for p in playlists if p.playlistType == playlistType]
    if smart != None:
        playlists = [p for p in playlists if p.smart == smart]
    playlists = sorted(playlists, key=lambda x: x.title)

    if not playlists:
        print('No Playlist available')
        return

    playlist = None
    if choice == None:
        print('\r\033[KChoose Playlist:')
        for i, p in enumerate(playlists):
            print('{}: {}, {} items, {}, added on {}'.
                format(i,
                        p.title,
                        p.leafCount,
                        datetime.timedelta(milliseconds=(p.duration if p.duration else 0)),
                        p.addedAt))

        choice = input('Playlist: ')
        try:
            playlist = playlists[int(choice)]
        except (ValueError, IndexError):
            try:
                playlist = next((p for p in playlists if p.title.lower() == choice.lower()), None)
            except:
                pass

            if playlist == None:
                return select_playlist(plex, playlistType, smart, None)
    else:
        try:
            playlist = next((p for p in playlists if p.title.lower() == choice.lower()), None)
            if playlist == None and multiple:
                try:
                    pattern = re.compile(choice, re.IGNORECASE)
                except:
                    print(f"\r\033[K'{choice}' is not a valid regex pattern!")
                    return
                filtered_playlists = [p for p in playlists if pattern.search(p.title)]
                print(f'\r\033[KPlaylists: {', '.join(p.title for p in filtered_playlists)}')
                return filtered_playlists
        except:
            pass

        if playlist == None:
            print(f"\r\033[KPlaylist '{choice}' not found!")
            return

    print(f'\r\033[KPlaylist: {playlist.title}')
    print("Loading playlist...", end="\r", flush=True)
    return playlist


def select_server(account):
    """
    Allows the user to choose a plex server.
    When only 1 server is available that one is used without confirmation.
    """
    servers = [f for f in account.resources() if 'server' in f.provides]
    if len(servers) == 0:
        raise Exception("Your account has no access to a plex server!")
    elif len(servers) == 1:
        return servers[0]
    else:
        print('Choose Server:')
        for index, server in enumerate(servers):
            print(f"{index}: {server.name}")

        choice = input('Server: ')
        server = None
        try:
            server = servers[int(choice)]
        except (ValueError, IndexError):
            try:
                server = next((s for s in servers if s.name.lower() == choice.lower()), None)
            except:
                pass

        if server == None:
            return select_server(account)

        return server


def select_user(plex, choice: Optional[str] = None):
    """
    Returns one of the MyPlexUser's ("Friends") accounts that have access to the server.
    Can be used to access their playlist.
    """
    myPlexAccount = plex.myPlexAccount()
    users = [myPlexAccount] + myPlexAccount.users()

    user = None
    if choice == None:
        print('\r\033[KChoose User:')
        for i, u in enumerate(users):
            print(f'{i}: {u.username} ({u.email})')

        choice = input('User: ')
        try:
            user = users[int(choice)]
        except (ValueError, IndexError):
            try:
                user = next((u for u in users if (u.username.lower() == choice.lower()) or (u.email.lower() == choice.lower())), None)
            except:
                pass

            if user == None:
                return select_user(plex, choice)
    else:
        try:
            user = next((u for u in users if (u.username.lower() == choice.lower()) or (u.email.lower() == choice.lower())), None)
        except:
            pass
        if user == None:
            print(f"\r\033[KUser '{choice}' not found!")
            return

    print(f'\r\033[KUser: {user.username} ({user.email})')
    print("Connecting with user token...", end="\r", flush=True)
    token = getattr(user, 'authenticationToken', False)
    if not token:
        token = user.get_token(plex.machineIdentifier)
    return PlexServer(plex._baseurl, token)


def size_str(sizeBytes):
    """
    Converts the size to human readable format.
    """
    if sizeBytes == 0:
        return "0B"
    sizeName = ("iB", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB")
    i = int(math.floor(math.log(sizeBytes, 1024)))
    p = math.pow(1024, i)
    s = round(sizeBytes / p, 2)
    return "{:0.2f} {}".format(s, sizeName[i])


def unique_path(section, item, media_ix=0, part_ix=0):
    """
    Returns the folder and filename of the item on the server, but without the section's location prefix.
    This should result in a unique path for downloading those files.
    i.e. '/data/movies/video (year)/video (year).mkv' -> 'video (year)/video (year).mkv'
    """
    # the path can be linux and the script runs on windows or vice versa
    # so the paths are normalized to the OS running this script
    file = os.path.normpath(item.media[media_ix].parts[part_ix].file)
    for location in section.locations:
        loc = os.path.normpath(location)
        loc = os.path.join(loc, "").lower() # the join forces a trailing path separator
        if file.lower().startswith(loc):
            # remove location from path, check each part for illegal characters
            path = ''
            for part in file[len(loc):].split(os.sep):
                path = os.path.join(path, clean_path_part(part))
            return path


def handle_sigint(signal_received, frame):
    print("\nStopped by user (Ctrl+C)")
    sys.exit(0)

# Install Ctrl+C signal handler for all scripts
signal.signal(signal.SIGINT, handle_sigint)