#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import io
import json
import os
import requests
import shutil
import subprocess
import time

import mutagen
import mutagen.mp4

# Supress pafy errors and override of logging settings
os.environ['PAFY_BACKEND'] = 'internal'
import pafy # http://np1.github.io/pafy/

import soundcloud
from lxml.html import fromstring
import pprint
import re


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
        # Telegram on android fails on scrolling mp4 tracks
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
    log.debug('Downloading %r -> %r', url, filename)
    response = requests.get(url)
    statusCode = response.status_code
    if statusCode == 200:
        log.debug('Got code 200, writing content')
        with open(filename, 'w') as f:
            f.write(response.content)
        log.debug('Content is ready')
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
        bitrate = '128000'
        command = [
            'ffmpeg',
            '-loglevel', '0', # lower ffmeg's verbosity
            '-i', tmpFile,
            '-f', 'mp3',
            '-b:a', bitrate,
            '-ar', '44100', # output will have 44100 Hz
            '-ac', '2', # stereo (set to '1' for mono)
            '-vn', # no video
            '-y', # overwrite output
        ]
        if self.StartShift is not None:
            command += ['-ss', self.StartShift]
        command.append(filename)
        log.debug('Running %r', command)
        result = subprocess.call(command)
        if result != 0:
            raise 'Convert to mp3 failed'
        else:
            os.remove(tmpFile)
            self.AudioFormat = 'mp3'
            log.info('Converted to mp3, bitrate is {}'.format(bitrate))


class Mp3Track(Track):
    def __init__(self, audioUrl):
        self.AudioUrl = audioUrl

    def Download(self, filename):
        downloadUrl(self.AudioUrl, filename)


class ShlosbergLive(object):
    def __init__(self):
        pass

    def FormTitle(self, goodTitle, title, date, part):
        if goodTitle:
            topic = goodTitle
        else:
            if u'«' in title:
                parts = [p for p in re.split('[«»]', title) if p]
            else:
                parts = title.split('.', 1)
            if len(parts) != 2:
                log.warn(u'Raw title: %s', title)
                raise RuntimeError('Broken title')
            subTitle = u' '.join(parts[2:]).strip().strip('.')
            if subTitle:
                subTitle = u'. {}'.format(subTitle)
            topic = u'Тема: «{}»{}'.format(
                parts[1].strip(),
                subTitle,
            )
        topic = u'Live #{}. {} ({})'.format(part, topic, date.replace('-', '/'))
        topic = topic.replace('  ', ' ')
        return topic

    def __call__(self):
        for url, part, shift, customTitle in self.Urls():
            ok = False
            log.debug('Trying to fetch %r, %r, %r', url, part, shift)
            while not ok:
                try:
                    video = pafy.new(url)
                    ok = True
                except IndexError:
                    sleepTime = 1200
                    log.info('Failed, sleeping for %d', sleepTime)
                    time.sleep(sleepTime)
            audio = video.getbestaudio(preftype='m4a')
            title = video.title
            youtubeTrack = Mp4Track(audio.url, shift)
            date = video.published[0:10]
            youtubeTrack.SetEverything(
                title=self.FormTitle(customTitle, video.title, date, part),
                # artist=video.author,
                artist=u'Лев Шлосберг',
                artistEng='grazhdanin-tv',
                playlist='shlosberg-live',
                created=date,
                permalink='shlosberg-live-{}'.format(part),
                permalinkUrl=url,
                audioFormat='mp4',
            )
            yield youtubeTrack

    def Urls(self):
        log.info('Videos from https://www.youtube.com/user/PskovYablokoTV/videos chosen manually')
        return [
            ('https://www.youtube.com/watch?v=OAxFXXYIPQE', '50', '0:23',   u'World of Tanks Владимира Путина'),
            ('https://www.youtube.com/watch?v=j_Fbry3k1kA', '49', '0:15',   u'Политический террор'),
            ('https://www.youtube.com/watch?v=4_eeEu52_6s', '48', '0:26',   u'На Сирийском фронте без перемен'),
            ('https://www.youtube.com/watch?v=i4HI2WCcyhA', '47', '0:25',   u'Гости: Галина Ширшина, политик и общественный деятель'),
            ('https://www.youtube.com/watch?v=5C633UtQvuM', '46', '0:24',   u'Российская социология сегодня. Кому верить?'),
            ('https://www.youtube.com/watch?v=nwshzE7pmRY', '45', '0:13',   u'Явлинский в Пскове и Гдове. Послесловие'),
            ('https://www.youtube.com/watch?v=qo54lWAK1H0', '44', '0:20',   u'Гости: Григорий Явлинский'),
            ('https://www.youtube.com/watch?v=Ya20fvMFPqc', '43', '0:03',   u'Забастовка или Явлинский'),
            ('https://www.youtube.com/watch?v=bU-HBajBkYc', '42', '0:09',   u'Насилие в школах. Почему об этом молчит телевидение'),
            ('https://www.youtube.com/watch?v=vwyGAGulRoc', '41', '0:11',   u'100 лет без законной власти'),
            ('https://www.youtube.com/watch?v=HK6Yc5az-gA', '40', '0:11',   u'Назад в СССР?'),
            ('https://www.youtube.com/watch?v=d_rT1_fhwBY', '39', '0:11',   u'2017. Политические итоги года'),
            ('https://www.youtube.com/watch?v=okfbGIXxlQE', '38', '0:19',   u'Президент 2018. Личный выбор между добром и злом'),
            ('https://www.youtube.com/watch?v=HuKCihT4P64', '37', '0:26',   u'Кто победил в Сирии?'),
            ('https://www.youtube.com/watch?v=zKi__hj_apc', '36', '0:37',   u'Путин хочет еще'),
            ('https://www.youtube.com/watch?v=0_h7w_JC6f4', '35', '0:09',   u'Допинг. Медали ценой чести и здоровья'),
            ('https://www.youtube.com/watch?v=XmdVz34VuV4', '34', '0:05',   u'Собянин или Россия'),
            ('https://www.youtube.com/watch?v=cUgP2C7Y7mM', '33', '0:19',   u'Правда как иностранный агент'),
            ('https://www.youtube.com/watch?v=CuiADlYfjq0', '32', '1:52',   u'Гости: Юрий Павлов, избранный глава Гдовского района'),
            ('https://www.youtube.com/watch?v=7pkAydybFCc', '31', '0:10',   u'1917. Переворот истории. Что делать сейчас?'),
            ('https://www.youtube.com/watch?v=ofL2yRqw9f0', '30.2', None,   u'Политические репрессии сегодня. Вторая часть'),
            ('https://www.youtube.com/watch?v=YVSGDJov7cw', '30.1', '0:08', u'Политические репрессии сегодня. Первая часть'),
            ('https://www.youtube.com/watch?v=XXusqj6xygc', '29', '1:02',   u'Гости: Александр Конашенков, фермер, депутат Гдовского района'),
            ('https://www.youtube.com/watch?v=QBsjBcqFev0', '28', '0:54',   u'Гости: Виталий Аршинов, глава Плюсского района'),
            ('https://www.youtube.com/watch?v=YttJ60SY7sM', '27', '0:50',   u'Отставка Андрея Турчака'),
            ('https://www.youtube.com/watch?v=JPxS1wIjUmc', '26', '1:08',   u'7/31. Свобода собраний каждый день'),
            ('https://www.youtube.com/watch?v=QYwTmlN0UdE', '25', '1:06',   u'Как депутаты боролись с индексацией зарплат бюджетников'),
            ('https://www.youtube.com/watch?v=jv_B1PXiQB8', '24', '1:08',   u'Матильда Российской империи'),
            ('https://www.youtube.com/watch?v=owBdz-X_SWQ', '23', '1:47',   u'Как мы потратили ваши деньги'),
            ('https://www.youtube.com/watch?v=HWd9l03xp1k', '22', '1:34',   u'10 сентября 2017 года. Итоги'),
            ('https://www.youtube.com/watch?v=ZhmZghs89wA', '21', '2:15',   u'Избирательный бюллетень - главное оружие гражданина'),
            ('https://www.youtube.com/watch?v=72DIC22v1W4', '20', '1:16',   u'Дело Кирилла Серебренникова'),
            ('https://www.youtube.com/watch?v=yXK-AZd2HAw', '19', '0:34',   u'1991. После августа. Почему демократия не победила'),
            ('https://www.youtube.com/watch?v=fTyN66Sd9Fs', '18', '2:45',   u'Мы ждем перемен? Обсуждение исследования ВЦИОМ'),
            ('https://www.youtube.com/watch?v=wov7yvgTEok', '17', '1:18',   u'Рыбалка Путина'),
            ('https://www.youtube.com/watch?v=-h_KXVWVEJg', '16', '0:15',   u'Большой Террор. Преступники и наследники. 1937-2017'),
            ('https://www.youtube.com/watch?v=xb0AsPuGvuc', '15', '0:49',   u'Бюллетень или вилы: почему надо участвовать в выборах'),
            ('https://www.youtube.com/watch?v=p2jOsznpVrk', '14', '0:08',   u'Дело Немцова: вопросы без ответов'),
            ('https://www.youtube.com/watch?v=x5RDW-SXKA0', '13', '2:35',   u'Огонь по штабам'),
            ('https://www.youtube.com/watch?v=pu_l_4FrRQI', '12', '1:01',   u'Сталин сегодня'),
            ('https://www.youtube.com/watch?v=GxkhHqTKAlU', '11', '2:17',   u'Большой брат следит за тобой'),
            ('https://www.youtube.com/watch?v=Kf6AZOuj9dg', '10', '0:45',   u'«Прямая линия» Путина: царь есть, государства нет'),
            ('https://www.youtube.com/watch?v=23vjnCTlTjc', '9.2', '0:15',  u'Акции протеста в современной России. Вторая часть'),
            ('https://www.youtube.com/watch?v=i0-AI04ZYes', '9.1', '0:59',  u'Акции протеста в современной России. Первая часть'),
            ('https://www.youtube.com/watch?v=jkN6Af4m9x8', '8', '0:15',    u'Возвращение прямых выборов мэров в городах России'),
            ('https://www.youtube.com/watch?v=DivQCLyu_6s', '7', '0:36',    u'Спор Шлосберга с Навальным'),
            ('https://www.youtube.com/watch?v=j7rL2jqhZnE', '6', '0:35',    u'Прямой эфир'),
            ('https://www.youtube.com/watch?v=fslL0Sjgz5U', '5', '1:36',    u'Прямой эфир'),
            ('https://www.youtube.com/watch?v=EP_ljk6sZvU', '4', '0:41',    u'Прямой эфир'),
            ('https://www.youtube.com/watch?v=jVj9L8KD3eA', '3', '0:39',    u'Прямой эфир'),
            ('https://www.youtube.com/watch?v=COhG3aHOs58', '2', '1:12',    u'Прямой эфир'),
            ('https://www.youtube.com/watch?v=X0mPF5HwaFs', '1', '36:20',   u'Прямой эфир'),
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
        log.info('Getting soundcloud tracks')
        soundcloudDownloader = SoundcloudDownloader(soundcloudToken)
        for playlistUrl, playlistName, customPrefixDict in soundcloudDownloader.Sets():
            for track in soundcloudDownloader(
                playlistUrl,
                playlistName=playlistName,
                customPrefixDict=customPrefixDict
            ):
                yield track

    if args.shlosberg_live:
        log.info('Getting Shlosberg tracks')
        shlosbergLive = ShlosbergLive()
        for track in shlosbergLive():
            yield track

    if args.openuni:
        log.info('Getting OpenUni tracks')
        openUni = OpenUniversity()
        for track in openUni():
            yield track


def main(args):
    log.info('Main')
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
            ok = False
            while not ok:
                try:
                    result = track.Save(downloadPath, force=args.force)
                    ok = True
                except IndexError:
                    sleepTime = 1200
                    log.info('Failed, sleeping for %d', sleepTime)
                    time.sleep(sleepTime)


            saved += int(result)
        else:
            log.info('File wasn\'t saved')
    log.info('Checked {} files, saved {} of them'.format(checked, saved))


def CreateArgumentsParser():
    parser = argparse.ArgumentParser('Download playlists', formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    saveGroup = parser.add_argument_group('Saving files arguments')
    saveGroup.add_argument('--save', help='Actually save files', action='store_true')
    saveGroup.add_argument('--force', help='Force save even for existing files', action='store_true')

    podcastsGroup = parser.add_argument_group('Podcasts arguments')
    podcastsGroup.add_argument('--soundcloud', help='Download soundcloud', action='store_true')
    podcastsGroup.add_argument('--shlosberg-live', help='Download Shlosberg Live', action='store_true')
    podcastsGroup.add_argument('--openuni', help='Download Open University', action='store_true')
    podcastsGroup.add_argument('--secrets', help='File with custom settings', default='secrets.json')

    loggingGroup = parser.add_argument_group('Logging arguments')
    loggingGroup.add_argument('--log-format', help='Logging str', default='%(asctime)s %(name)15s:%(lineno)3d [%(levelname)s] %(message)s')
    loggingGroup.add_argument('--log-separator', help='Logging string separator', choices=['space', 'tab'], default='space')
    loggingGroup.add_argument('--verbose', help='Enable debug logging', action='store_true')

    return parser


if __name__ == '__main__':
    parser = CreateArgumentsParser()
    args = parser.parse_args()

    logFormat = args.log_format.replace('\t', ' ')
    logFormat = logFormat.replace(' ', {'space': ' ', 'tab': '\t'}[args.log_separator])
    logLevel = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=logLevel, format=logFormat)

    log.info('Start')
    main(args)
    log.info('Finish')
