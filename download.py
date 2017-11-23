#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import io
import os
import requests
import json

import mutagen
import mutagen.mp4
import pafy # http://np1.github.io/pafy/
import soundcloud

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
    ):
        self.Title = title
        self.Created = created
        self.Permalink = permalink          # uniq id
        self.PermalinkUrl = permalinkUrl    # url for caption
        self.Artist = artist
        self.ArtistEng = artistEng.replace(' ', '_') # for hashtag
        self.Playlist = playlist # for hashtag
        self.AudioFormat = audioFormat

    def Download(self, filename):
        raise NotImplementedError()

    def Filename(self):
        # Telegram needs mp3 extension to show mp4 files as audio
        # Android fails on scrolling mp4 tracks
        return os.path.join(
            self.ArtistEng,
            self.Playlist,
            '{track.Created}-{track.Permalink}.mp3'.format(track=self)
        )

    def TelegramCaption(self):
        return u'#{artistEng} #{playlistName} [{track.Created}] {track.Title}\n{track.PermalinkUrl}'.format(
            artistEng=self.ArtistEng.replace('-', '_'),
            track=self,
            playlistName=self.Playlist.replace('-', '_'),
        )

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
            log.info('File {!r} exists, skipping'.format(filename))
            return
        try:
            self.Download(filename)
        except DownloadError:
            log.exception('Download failed')
            raise
        self.Tag(filename)
        log.info('File {} was saved, meta was updated'.format(filename))


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

    def __call__(self, playlistUrl, playlistName=None):
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
            log.info(u'Playlist "{}" ({}) of {} tracks'.format(playlistFields['title'], playlistPermalink, len(tracks)))
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
            ('https://soundcloud.com/inliberty/sets/ya-mogu-govorit', None),
            ('https://soundcloud.com/inliberty/sets/fj1fjsmauyke', 'public-lie'),
        ]


class YoutubeTrack(Track):
    def __init__(self, audioUrl):
        self.AudioUrl = audioUrl

    def Download(self, filename):
        # TODO: convert to mp3
        assert self.AudioFormat == 'mp4'
        downloadUrl(self.AudioUrl, filename)


class ShlosbergLive(object):
    def __init__(self):
        pass

    def __call__(self):
        for url, part in self.Urls():
            video = pafy.new(url)
            audio = video.getbestaudio(preftype='m4a')
            title = video.title
            youtubeTrack = YoutubeTrack(audio.url)
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
        log.info('Videos from https://www.youtube.com/user/PskovYablokoTV/videos')
        return [
            ('https://www.youtube.com/watch?v=CuiADlYfjq0', '32'),
            # ('https://www.youtube.com/watch?v=7pkAydybFCc', '31'),
            # ('https://www.youtube.com/watch?v=ofL2yRqw9f0', '30-2'),
            # ('https://www.youtube.com/watch?v=YVSGDJov7cw', '30-1'),
            # ('https://www.youtube.com/watch?v=XXusqj6xygc', '29'),
            # ('https://www.youtube.com/watch?v=QBsjBcqFev0', '28'),
            # ('https://www.youtube.com/watch?v=YttJ60SY7sM', '27'),
            # ('https://www.youtube.com/watch?v=JPxS1wIjUmc', '26'),
            # ('https://www.youtube.com/watch?v=QYwTmlN0UdE', '25'),
            # ('https://www.youtube.com/watch?v=jv_B1PXiQB8', '24'),
            # ('https://www.youtube.com/watch?v=owBdz-X_SWQ', '23'),
            # ('https://www.youtube.com/watch?v=HWd9l03xp1k', '22'),
            # ('https://www.youtube.com/watch?v=ZhmZghs89wA', '21'),
            # ('https://www.youtube.com/watch?v=72DIC22v1W4', '20'),
            # ('https://www.youtube.com/watch?v=yXK-AZd2HAw', '19'),
            # ('https://www.youtube.com/watch?v=fTyN66Sd9Fs', '18'),
            # ('https://www.youtube.com/watch?v=wov7yvgTEok', '17'),
            # ('https://www.youtube.com/watch?v=-h_KXVWVEJg', '16'),
            # ('https://www.youtube.com/watch?v=xb0AsPuGvuc', '15'),
            # ('https://www.youtube.com/watch?v=p2jOsznpVrk', '14'),
            # ('https://www.youtube.com/watch?v=x5RDW-SXKA0', '13'),
            # ('https://www.youtube.com/watch?v=pu_l_4FrRQI', '12'),
            # ('https://www.youtube.com/watch?v=GxkhHqTKAlU', '11'),
            # ('https://www.youtube.com/watch?v=Kf6AZOuj9dg', '10'),
            # ('https://www.youtube.com/watch?v=23vjnCTlTjc', '9-2'),
            # ('https://www.youtube.com/watch?v=i0-AI04ZYes', '9-1'),
            # ('https://www.youtube.com/watch?v=jkN6Af4m9x8', '8'),
            # ('https://www.youtube.com/watch?v=DivQCLyu_6s', '7'),
            # ('https://www.youtube.com/watch?v=j7rL2jqhZnE', '6'),
            # ('https://www.youtube.com/watch?v=fslL0Sjgz5U', '5'),
            # ('https://www.youtube.com/watch?v=EP_ljk6sZvU', '4'),
            # ('https://www.youtube.com/watch?v=jVj9L8KD3eA', '3'),
            # ('https://www.youtube.com/watch?v=COhG3aHOs58', '2'),
            # ('https://www.youtube.com/watch?v=X0mPF5HwaFs', '1'),
        ]


def getTracks(args, soundcloudToken=None):
    if args.soundcloud:
        soundcloudDownloader = SoundcloudDownloader(soundcloudToken)
        for playlistUrl, playlistName in soundcloudDownloader.Sets():
            for track in soundcloudDownloader(playlistUrl, playlistName):
                yield track

    if args.shlosberg_live:
        shlosbergLive = ShlosbergLive()
        for track in shlosbergLive():
            yield track


def main(args):
    with open(args.secrets) as f:
        secrets = json.load(f)
    for track in getTracks(args, soundcloudToken=secrets['SoundcloudToken']):
        logMessage = track.LogMessage()
        log.info(logMessage)
        if args.save:
            try:
                track.Save(os.path.join(os.sep, *secrets['DownloadPath']))
            except DownloadError:
                pass
            # else:
            #     with io.open('log.txt', 'a+') as f:
            #         f.write(logMessage)
        else:
            log.info('File wasn\'t saved')


def CreateArgumentsParser():
    parser = argparse.ArgumentParser('Download playlists', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--debug', help='Debug logging', action='store_true')
    parser.add_argument('--soundcloud', help='Download soundcloud', action='store_true')
    parser.add_argument('--shlosberg-live', help='Download Shlosberg Live', action='store_true')
    parser.add_argument('--save', help='Actually save files', action='store_true')
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
