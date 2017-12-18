#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import io
import json
import os
import requests
import shutil
import subprocess

import mutagen
import mutagen.mp4
import pafy # http://np1.github.io/pafy/
import soundcloud
from lxml.html import fromstring
import pprint   


import logging
log = logging.getLogger(__file__)


class DownloadError(Exception):
    pass


class Track(object):
    def SetEverything(self,
        title=None,
        created=None,
        permalink=None,
        permalinkUrl=None,
        artist=None,
        artistEng=None,
        playlist=None,
        audioFormat=None,
        customPrefixDict=None,
    ):
        self.Title = title
        self.Created = created
        self.Permalink = permalink          # uniq id
        self.PermalinkUrl = permalinkUrl    # url for caption
        self.Artist = artist
        self.ArtistEng = artistEng.replace(' ', '_') # for hashtag
        self.Playlist = playlist # for hashtag
        self.AudioFormat = audioFormat
        self.CustomPrefixDict = customPrefixDict

    def Download(self, filename):
        raise NotImplementedError()

    def Filename(self):
        # Telegram needs mp3 extension to show mp4 files as audio
        # Android fails on scrolling mp4 tracks
        prefix = ''
        if self.CustomPrefixDict is not None:
            for key, value in self.CustomPrefixDict.iteritems():
                lowerKey = key.lower()
                if lowerKey in self.Permalink.lower() or lowerKey in self.Title.lower():
                    if prefix:
                        raise RuntimeError('Duplicated prefix')
                    else:
                        prefix = '{}-'.format(value)

        basename = u'{prefix}{track.Created}-{track.Permalink}.mp3'.format(prefix=prefix, track=self).replace(':', u' —')
        log.debug(u'Basename is {}'.format(basename))
        return os.path.join(self.ArtistEng, self.Playlist, basename)

    def TelegramCaption(self):
        telegramCaption = u'#{artistEng} #{playlistName} [{track.Created}] {track.Title}\n{track.PermalinkUrl}'.format(
            artistEng=self.ArtistEng.replace('-', '_'),
            track=self,
            playlistName=self.Playlist.replace('-', '_'),
        )
        log.debug(u'Telegram caption is {}'.format(telegramCaption))
        return telegramCaption

    def LogMessage(self):
        return u'''
Artist:\t\t{track.Artist}
ArtistEng:\t{track.ArtistEng}
Playlist:\t{track.Playlist}
Title:\t\t{track.Title}
Created:\t{track.Created}
Permalink:\t{track.Permalink}
Permalink URL:\t{track.PermalinkUrl}
Filename:\t{filename}
Telegram caption:\n{telegramCaption}
'''.format(
    track=self,
    filename=self.Filename(),
    telegramCaption=self.TelegramCaption()
)

    def Tag(self, filename):
        if self.AudioFormat == 'mp3':
            audio = mutagen.File(filename, easy=True)
            audio['artist'] = self.Artist
            audio['title'] = self.Title
        elif self.AudioFormat == 'mp4':
            audio = mutagen.mp4.MP4(filename)
            audio['\xa9ART'] = self.Artist
            audio['\xa9nam'] = self.Title
        else:
            raise RuntimeError('Invalid audio format: {!r}'.format(self.AudioFormat))
        audio.save()

    def Save(self, dstDir, force=None):
        filename = os.path.join(dstDir, self.Filename())
        if not force and os.path.exists(filename):
            log.info(u'File {} exists, skipping'.format(filename))
            return False
        self.Download(filename)
        self.Tag(filename)
        log.info(u'File {} was saved, meta was updated'.format(filename))
        return True


def downloadUrl(url, filename):
    response = requests.get(url)
    statusCode = response.status_code
    if statusCode == 200:
        with open(filename, 'w') as f:
            f.write(response.content)
    else:
        raise DownloadError('Got invalid response: {}'.format(statusCode))


class SoundcloudTrack(Track):
    def __init__(self, soundcloudClient, trackId):
        self.SoundcloudClient = soundcloudClient
        self.TrackId = trackId

    def Download(self, filename):
        stream = self.SoundcloudClient.get('/tracks/{}/stream'.format(self.TrackId), allow_redirects=False)
        downloadUrl(stream.location, filename)


class SoundcloudDownloader(object):
    def __init__(self, clientId):
        self.SoundcloudClient = soundcloud.Client(client_id=clientId)

    def __call__(self, playlistUrl, playlistName=None, customPrefixDict={}):
        artist, playlist = self.ParseSetUrl(playlistUrl)
        log.info('Looking for playlist {!r} of user {!r}'.format(playlist, artist))
        playlists = self.SoundcloudClient.get('/users/{}/playlists'.format(artist))
        for playlistRaw in playlists:
            playlistFields = playlistRaw.fields()
            tracks = playlistFields['tracks']
            playlistPermalink = playlistFields['permalink']
            if playlistPermalink != playlist:
                log.info('Skipping playlist {!r}'.format(playlistPermalink))
                continue
            log.info(u'Playlist {!r} ({}) of {} tracks'.format(playlistFields['title'], playlistPermalink, len(tracks)))
            for track in tracks:
                soundcloudTrack = SoundcloudTrack(self.SoundcloudClient, track['id'])
                soundcloudTrack.SetEverything(
                    title=track['title'],
                    artist=artist,
                    artistEng=artist,
                    playlist=playlistName or playlist,
                    created=track['created_at'].replace('/', '-')[0:10],
                    permalink=track['permalink'],
                    permalinkUrl=track['permalink_url'],
                    audioFormat='mp3',
                    customPrefixDict=customPrefixDict
                )
                yield soundcloudTrack

    def ParseSetUrl(self, url):
        parts = url.strip('/').split('/')
        artist = parts[-3]
        assert parts[-2] == 'sets'
        playlist = parts[-1]
        return artist, playlist

    def Sets(self):
        return [
            # ('https://soundcloud.com/inliberty/sets/ya-mogu-govorit', None),
            ('https://soundcloud.com/inliberty/sets/fj1fjsmauyke', 'public-lie', {
                'zorin': 3,
                'shulman': 6,
                'titaev': 1 ,
                'panchenko': 4,
                'chabovskii': 5,
                'gelfand': 2,
                'levontina': 8,
                'klyucharev': 7,
            }),
        ]


def toShift(shift):
    if shift is None:
        result = None
    else:
        result = 0
        for item in shift.split(':'):
            result = result * 60 + int(item)
        result = str(result)
    log.debug('Shift from {!r} is {!r}'.format(shift, result))
    return result


class Mp4Track(Track):
    def __init__(self, audioUrl, startShift=None):
        self.AudioUrl = audioUrl
        self.StartShift = toShift(startShift)

    def Download(self, filename):
        assert self.AudioFormat == 'mp4'
        tmpFile = filename + '.tmp'
        downloadUrl(self.AudioUrl, tmpFile)
        # https://github.com/Top-Dog/Python-MP4-to-MP3-Converter/blob/master/Python-MP4-to-MP3-Converter/Python-MP4-to-MP3-Converter/main.py#L109
        command = [
            'ffmpeg',
            '-loglevel', '0', # lower ffmeg's verbosity
            '-i', tmpFile,
            '-f', 'mp3',
            '-b:a', '192000',
            '-ar', '44100', # output will have 44100 Hz
            '-ac', '2', # stereo (set to '1' for mono)
            '-vn', # no video
            '-y', # overwrite output
        ]
        if self.StartShift is not None:
            command += ['-ss', self.StartShift]
        command.append(filename)
        result = subprocess.call(command)
        if result != 0:
            raise 'Convert to mp3 failed'
        else:
            os.remove(tmpFile)
            self.AudioFormat = 'mp3'
            log.info('Converted to mp3')


class Mp3Track(Track):
    def __init__(self, audioUrl):
        self.AudioUrl = audioUrl

    def Download(self, filename):
        downloadUrl(self.AudioUrl, filename)


class ShlosbergLive(object):
    def __init__(self):
        pass

    def __call__(self):
        for url, part, shift in self.Urls():
            video = pafy.new(url)
            audio = video.getbestaudio(preftype='m4a')
            title = video.title
            youtubeTrack = Mp4Track(audio.url, shift)
            youtubeTrack.SetEverything(
                title=video.title,
                artist=video.author,
                artistEng='grazhdanin-tv',
                playlist='shlosberg-live',
                created=video.published[0:10],
                permalink='shlosberg-live-{}'.format(part),
                permalinkUrl=url,
                audioFormat='mp4',
            )
            yield youtubeTrack

    def Urls(self):
        log.info('Videos from https://www.youtube.com/user/PskovYablokoTV/videos chosen manually')
        return [
            ('https://www.youtube.com/watch?v=HuKCihT4P64', '37', '0:26'),
            ('https://www.youtube.com/watch?v=zKi__hj_apc', '36', '0:37'),
            ('https://www.youtube.com/watch?v=0_h7w_JC6f4', '35', '0:09'),
            ('https://www.youtube.com/watch?v=XmdVz34VuV4', '34', '0:05'),
            ('https://www.youtube.com/watch?v=cUgP2C7Y7mM', '33', '0:19'),
            ('https://www.youtube.com/watch?v=CuiADlYfjq0', '32', '1:52'),
            ('https://www.youtube.com/watch?v=7pkAydybFCc', '31', '0:10'),
            ('https://www.youtube.com/watch?v=ofL2yRqw9f0', '30-2', None),
            ('https://www.youtube.com/watch?v=YVSGDJov7cw', '30-1', '0:08'),
            ('https://www.youtube.com/watch?v=XXusqj6xygc', '29', '1:02'),
            ('https://www.youtube.com/watch?v=QBsjBcqFev0', '28', '0:54'),
            ('https://www.youtube.com/watch?v=YttJ60SY7sM', '27', '0:50'),
            ('https://www.youtube.com/watch?v=JPxS1wIjUmc', '26', '1:08'),
            ('https://www.youtube.com/watch?v=QYwTmlN0UdE', '25', '1:06'),
            ('https://www.youtube.com/watch?v=jv_B1PXiQB8', '24', '1:08'),
            ('https://www.youtube.com/watch?v=owBdz-X_SWQ', '23', '1:47'),
            ('https://www.youtube.com/watch?v=HWd9l03xp1k', '22', '1:34'),
            ('https://www.youtube.com/watch?v=ZhmZghs89wA', '21', '2:15'),
            ('https://www.youtube.com/watch?v=72DIC22v1W4', '20', '1:16'),
            ('https://www.youtube.com/watch?v=yXK-AZd2HAw', '19', '0:34'),
            ('https://www.youtube.com/watch?v=fTyN66Sd9Fs', '18', '2:45'),
            ('https://www.youtube.com/watch?v=wov7yvgTEok', '17', '1:18'),
            ('https://www.youtube.com/watch?v=-h_KXVWVEJg', '16', '0:15'),
            ('https://www.youtube.com/watch?v=xb0AsPuGvuc', '15', '0:49'),
            ('https://www.youtube.com/watch?v=p2jOsznpVrk', '14', '0:08'),
            ('https://www.youtube.com/watch?v=x5RDW-SXKA0', '13', '2:35'),
            ('https://www.youtube.com/watch?v=pu_l_4FrRQI', '12', '1:01'),
            ('https://www.youtube.com/watch?v=GxkhHqTKAlU', '11', '2:17'),
            ('https://www.youtube.com/watch?v=Kf6AZOuj9dg', '10', '0:45'),
            ('https://www.youtube.com/watch?v=23vjnCTlTjc', '9-2', '0:15'),
            ('https://www.youtube.com/watch?v=i0-AI04ZYes', '9-1', '0:59'),
            ('https://www.youtube.com/watch?v=jkN6Af4m9x8', '8', '0:15'),
            ('https://www.youtube.com/watch?v=DivQCLyu_6s', '7', '0:36'),
            ('https://www.youtube.com/watch?v=j7rL2jqhZnE', '6', '0:35'),
            ('https://www.youtube.com/watch?v=fslL0Sjgz5U', '5', '1:36'),
            ('https://www.youtube.com/watch?v=EP_ljk6sZvU', '4', '0:41'),
            ('https://www.youtube.com/watch?v=jVj9L8KD3eA', '3', '0:39'),
            ('https://www.youtube.com/watch?v=COhG3aHOs58', '2', '1:12'),
            ('https://www.youtube.com/watch?v=X0mPF5HwaFs', '1', '36:20'),
        ]


def dumpJson(data, index=None):
    if index is None:
        filename = 'tmp.json'
    else:
        filename = 'tmp{}.json'.format(index)
    with io.open(filename, 'w', encoding='utf8') as jsonFile:
        jsonFile.write(json.dumps(data, indent=4, sort_keys=True, ensure_ascii=False))


class OpenUniversity(object):
    def __init__(self):
        self.MainUrl = 'https://openuni.io'

    def GetInitialState(self, path):
        initialStatePrefix = 'window.__INITIAL_STATE__ = '
        url = '{}{}'.format(self.MainUrl, path)
        response = requests.get(url)
        assert response.status_code == 200, url
        rawHtml = response.text
        states = [script.text_content() for script in fromstring(rawHtml).iter('script') if script.text_content().startswith(initialStatePrefix)]
        assert len(states) == 1, rawHtml
        return json.loads(states[0][len(initialStatePrefix):])

    def __call__(self):
        res = self.GetInitialState('/')
        i = 0
        for courceId, courceProps in res['store']['courses']['byId'].iteritems():
            playlistName = {
                '1': 'culture-as-polytics',
                '2': 'big-transit',
                '3': 'road-to-market',
                '5': 'new-human',
                '6': 'restate',
                '7': 'after-empire',
            }.get(courceId)


            if playlistName is None:
                log.warn('Course {} is not supported'.format(courceId))
                continue
            else:
                playlistName = '{}-{}'.format(courceId, playlistName)
                log.info(u'Playlist {}: {} aka {}'.format(courceId, courceProps['title'], playlistName))

            assert courceProps['lessons_count'] == len(courceProps['lessons'])
            for index, lession in enumerate(courceProps['lessons']):
                lessionNumber = lession['number']
                assert (index + 1) == lessionNumber
                path = '/course/{}/lesson/{}/'.format(courceId, lessionNumber)
                tmp = self.GetInitialState(path)
                w = tmp['store']['lessons']['completeInfo'].values()
                assert len(w) == 1
                w = w[0]

                lecturers = []
                for lecturer in w['lecturers']:
                    lecturers.append(u'{} {}'.format(lecturer['first_name'], lecturer['last_name']))
                title = w['title']
                if u': «' not in title:
                    title = u'{}: «{}»'.format(
                        u' и '.join(lecturers),
                        title,
                    )
                audioUrl = u'{}{}'.format(w['audio'], w['audio_filename'])
                track = Mp3Track(audioUrl)
                track.SetEverything(
                    title=title,
                    created='{:02}'.format(index + 1),
                    permalink=w['title'],
                    permalinkUrl='{}{}'.format(self.MainUrl, path),
                    artist=u'Открытый университет',
                    artistEng='openuni',
                    playlist=playlistName,
                    audioFormat='mp3',
                )
                yield track


def getTracks(args, soundcloudToken=None):
    if args.soundcloud:
        soundcloudDownloader = SoundcloudDownloader(soundcloudToken)
        for playlistUrl, playlistName, customPrefixDict in soundcloudDownloader.Sets():
            for track in soundcloudDownloader(
                playlistUrl,
                playlistName=playlistName,
                customPrefixDict=customPrefixDict
            ):
                yield track

    if args.shlosberg_live:
        shlosbergLive = ShlosbergLive()
        for track in shlosbergLive():
            yield track

    if args.openuni:
        openUni = OpenUniversity()
        for track in openUni():
            yield track


def main(args):
    with io.open(args.secrets) as f:
        secrets = json.load(f)
    saved, checked = 0, 0
    downloadPath = os.path.join(os.sep, *secrets['DownloadPath'])
    log.info('Saving files to {!r}'.format(downloadPath))
    for track in getTracks(args, soundcloudToken=secrets['SoundcloudToken']):
        logMessage = track.LogMessage()
        log.info(logMessage)
        checked += 1
        if args.save:
            result = track.Save(downloadPath, force=args.force)
            saved += int(result)
        else:
            log.info('File wasn\'t saved')
    log.info('Checked {} files, saved {} of them'.format(checked, saved))


def CreateArgumentsParser():
    parser = argparse.ArgumentParser('Download playlists', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--debug', help='Debug logging', action='store_true')
    parser.add_argument('--soundcloud', help='Download soundcloud', action='store_true')
    parser.add_argument('--shlosberg-live', help='Download Shlosberg Live', action='store_true')
    parser.add_argument('--openuni', help='Download Open University', action='store_true')
    parser.add_argument('--save', help='Actually save files', action='store_true')
    parser.add_argument('--force', help='Force save even for existing files', action='store_true')
    parser.add_argument('--secrets', help='File with custom settings', default='secrets.json')
    return parser


if __name__ == '__main__':
    parser = CreateArgumentsParser()
    args = parser.parse_args()
    logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s')
    log.setLevel(logging.DEBUG if args.debug else logging.INFO)
    log.info('Start')
    main(args)
    log.info('Finish')
