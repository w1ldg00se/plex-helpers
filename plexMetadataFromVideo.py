#!/usr/bin/env python3
"""
Videos can have metadata like a thumbnail or a description embedded in the video file (at least for container formats like .mpv).
Many tools, i.e. ffmpeg or yt-dl/yt-dlp with the --embed-metadata and --embed-thumbnail options, can embed such metadata in videos.
Ples doesn't extract those, it doesn't even show them in the media info.
So this script updates metadata in plex with metadata extracted from the video file.

When an url is found in the description, it is added at the beginning of the summary (but sadly it isn't clickable as it is a plain text field which doesn't support html )
The summary is locked after a video was processed successfully.
To process a video again, remove the lock on the summary in the video options and remove the url at the beginning of the summary.

Dependencies: ffmpeg and ffprobe must be installed on the system.
"""

import argparse
import json
import os
import re
import requests
import tempfile
from pathlib import PurePath
from plexapi.collection import Collection
from tqdm import tqdm
from plexHelpers import plex_connect, run_command, select_section


# for removing youtube id from title
patternYTid = re.compile(r"\[[\S]+\]") # youtube video id (regex: '[...]' with a content of all except whitespace)


def get_video_info(filename):
    '''
    Uses ffprobe to extract metadata from the video file.

    Note: Extracts more information than needed here, but i already had this function in another script 
    and didn't bother to clean it up as extracting additional data from json shouldn't make much performance difference.
    '''

    artist = ''
    attachments = 0
    bitrate = 0
    bitrateAudio = 0
    channels = 0
    codec = ''
    description = ''
    filesize = 0
    languages = []
    tags = {}
    width = 0

    cmd = [
        "ffprobe",                           # ffprobe is from ffmpeg, can read video info
        "-v", "quiet",                       # hide ffprobe version, options, etc
        "-hide_banner",                      # hide banner
        "-print_format", "json",             # output json format
        "-show_entries", "format:stream",    # output all format end stream entries
        # "-show_entries", "format=bit_rate:stream=codec_name:stream=codec_type:stream=width:stream=channels",  # overall bitrate, stream codec type, width and channels
        filename,
    ]

    stdout, _, returncode = run_command(cmd, raiseException=False) # any error is handled in run_command
    if returncode == 0:
        d = json.loads(stdout)

        try:
            filesize = int(d['format']['size'])
        except:
            filesize = os.path.getsize(filename)
            pass

        try:
            bitrate = int(d['format']['bit_rate'])
        except:
            pass

        # add url to description
        try:
            description = d['format']['tags']['PURL'] + '\n\n'
        except:
            pass
        # comment mostly includes the same url as in PURL, so only add it when different
        try:
            comment = d['format']['tags']['COMMENT'] + '\n\n'
            if comment.lower() != description.lower():
                description += comment
        except:
            pass
        # add description
        try:
            description += d['format']['tags']['DESCRIPTION']
        except:
            pass

        # add artist
        try:
            artist += d['format']['tags']['ARTIST']
        except:
            pass

        # add tags
        try:
            tags = d['format']['tags']
        except:
            pass
        # make tags keys lowercase
        tags = {k.lower():v for k, v in tags.items()}

        # parse streams
        for stream in d['streams']:
            try:
                # there is usually only one video stream
                if stream['codec_type'] == 'video':
                    try:
                        width = stream['width']
                        codec = stream['codec_name']
                    except:
                        pass
                # parse audio streams (usually one or multiple)
                elif stream['codec_type'] == 'audio':
                    try:
                        # max channel count
                        if stream['channels'] > channels:
                            channels = stream['channels']
                    except:
                        pass

                    try:
                        # max channel bitrate
                        if int(stream['bit_rate']) > bitrateAudio:
                            bitrateAudio = int(stream['bit_rate'])
                    except:
                        pass

                    try:
                        # get audio languages
                        lang = stream['tags']['language'].lower()
                        if lang not in languages:
                            languages.append(lang)
                    except:
                        pass

                # get attachment count
                elif stream['codec_type'] == 'attachment':
                    attachments += 1
            except:
                pass

        return {
            'artist': artist,
            'attachments': attachments,
            'bitrate': bitrate,
            'bitrateAudio': bitrateAudio,
            'channels': channels,
            'codec': codec,
            'description': description,
            'filename': filename,
            'filesize': filesize,
            'languages': languages,
            'tags': tags,
            'width': width
        }


def set_embedded_thumbnail(item, file):
    """
    Extracts a thumbnail from the video and uploads it as a poster to plex.
    """

    # Attention: While being an official command from ffmpeg's documentation this command fails with "At least one output file must be specified" 
    # and thus exiting with exit code 1 (same as if no attachments available). It does extract available attachments though, so we just need
    # to check for new files.
    cmd = [
        "ffmpeg",                            # use ffmpeg to extract embedded thumbnail
        "-dump_attachment:t", "",            # this command extracts all attachments from the video container
        "-i", file                           # video file
    ]

    with tempfile.TemporaryDirectory() as tmpdir: # python automatically deletes this unique temporary directory after use
        stdout, _, returncode = run_command(cmd, raiseException=False, returncode=1, cwd=tmpdir)

        if returncode == 1: # yes, this ffmpeg command returns 1 on success and on failure
            attachments = os.listdir(tmpdir)
            if len(attachments) > 1:
                print(f'\r\033[K{item.title}: found multiple attachments: {attachments.join(', ')}')
                return
            for attachment in attachments:
                if PurePath(attachment).suffix.lower() in ['.jpg', '.webp']:
                    return item.uploadPoster(filepath=os.path.join(tmpdir, attachment)) # it's uploaded and set as default poster
                else:
                    print(f'\r\033[K{item.title}: found attachment of unknown type: {attachment}')
            return


def addEmbeddedMetadata(plex, item):
    """
    Downloads the first 2MB of the file, extracts metadata and updates the metadata in plex.
    """

    # Download up to 2MB in 256kB chunks and try to get video information via ffprobe.
    # This works on container files like mkv/mp4 where the file metadata is stored in the first 1-2MB.
    info = None
    byte_limit = 2*1024*1024 # 2MB or filesize when file is smaller
    chunk_size = 256*1024  # up to 8 chunks a'la 256kB (for most mkv files without thumbnail 256kB should be enough to parse metadata, mp4 needs >1MB)
    headers = {'Range': f'bytes=0-{byte_limit - 1}', 'X-Plex-Token': plex._token}
    for media in item.media:
        for part in media.parts:
            response = requests.get(f'{plex._baseurl}{part.key}', headers=headers, stream=True)
            with tempfile.NamedTemporaryFile() as tmp:
                for chunk in response.iter_content(chunk_size):
                    tmp.write(chunk)
                    tmp.flush() # needs flush because file is then read with external program 'ffprobe'

                    info = get_video_info(tmp.name)
                    if info:
                        if info['attachments'] > 0: # attached thumbnail available, extract as long as the temporary file is available
                            if set_embedded_thumbnail(item, tmp.name): # may need more than one chunk
                                break
                        else: break
                    # else: not enough data, continue downloading next chunk
            if info: break
        if info: break

    if not info:
        print(f'\r\033[K{item.title}: could not get metadata')
        return

    # set artist
    artist = info['artist']
    if artist:
        item.addProducer([artist], locked=True) # plex has no artist on video, so let's use the procuder field

    # set summary
    summary = info['description']
    if not summary:
        summary = item.summary
    item.editSummary(summary, locked=True)

    # remove youtube id from title
    match = patternYTid.search(item.title)
    if match and match.regs:
        item.editTitle(item.title[0:match.regs[0][0]-1], locked=True)


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

    items = []
    # filter out items where the summary starts with 'http' (fast) or the summary is locked (slow)
    # because in each of these cases it is assumed that metadata was already set
    for item in tqdm(section.all(), desc='\r\033[KFiltering...'):
        if (not item.summary.startswith('http') 
            and (not item.fields or not any(f.name == 'summary' and f.locked for f in item.fields))):
            items.append(item)

    print(f'\r\033[KFound {len(items)} items without metadata')

    # Ask for user confirmation before applying mood to all tracks
    if not args.yes:
        choice = input("Press Y to continue: ").strip().lower()
        if choice != 'y':
            print("Aborted.")
            exit(1)

    print(f'\r\033[KUpdating metadata in {section.title}...')
    for item in tqdm(items):
        addEmbeddedMetadata(plex, item)

    print("\r\033[KFinished")


if __name__ == '__main__':
    main()