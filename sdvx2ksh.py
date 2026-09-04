#!/usr/bin/env python3
# coding:utf-8
import sys
import urllib.request
import urllib.parse
from urllib.error import HTTPError
import numpy as np
import lxml.html
from io import BytesIO
import pafy
from PIL import Image
import os
import codecs
from pydub import AudioSegment
import re
import scipy.io.wavfile as wf
import cv2

###デバッグ用関数
show = lambda a: Image.fromarray(np.uint8(a)).show()
D = lambda l: [i-j for i,j in zip(l[:-1],l[1:])]

def toStr(arr):
	return '\r\n'.join(
		[
			''.join(i)
			for i in arr
		]
	)

def color_picker(arr):
	'''
	与えた領域に含まれる色とその量を表示する関数
	'''
	def rgba2hex(rgba):
		r, g, b, a = rgba
		R = r*6/256
		G = g*6/256
		B = b*6/256
		c = 36*R + 6*G + B + 16
		return "\033[48;5;"+str(c)+"m  \033[m"

	colors = [str(k) for k in arr.reshape((-1,4))]
	dic = {c:str(colors.count(c)) for c in set(colors)}
	for k in sorted(dic.items(), key=lambda x:int(x[1]), reverse=True):
		c = rgba2hex([int(i) for i in k[0][1:-1].split()])
		print(k[0] + ' : ' + c + ' : ' + str(k[1]))

###雑記
'''
color
ショート
黄縁(255,181,0)
黄(255,148,27,255)
ロング
黄(255,159,7,107)
黄赤(252,102,106)
17,37
12,22,32,42
 A or B or C ... の時はAを最もTrueになりやすいものにする
mt = np.r_[tuple(arr)]
'''

class Score:
	'''
	SOUND VOLTEXの譜面を表現するクラス
	インスタンス化の時はsdvx.inの譜面ページのurlを食べさせる
	'''
	def __init__(self, url):
		self.img = {}
		self.arr = {}
		self.url = {}
		self.header = {}

		old_url = re.match(
			r'^https?://(?:www\.)?sdvx\.in/(\d+)/(\d+)/(\d+)([naeigm])\.htm(?:\?.*)?$',
			url,
			re.I
		)

		new_url = re.match(
			r'^https?://(?:www\.)?sdvx\.in/(\d+)/(\d+)([naeigm])\.htm(?:\?.*)?$',
			url,
			re.I
		)

		if old_url:
			self.version = old_url.group(1)
			self.id = old_url.group(3)
			self._d = old_url.group(4).lower()
			self.path = '/'.join(url.split('/')[:4]) + '/'

		elif new_url:
			self.version = new_url.group(1)
			self.id = new_url.group(2)
			self._d = new_url.group(3).lower()
			self.path = '/'.join(url.split('/')[:4]) + '/'

		else:
			raise ValueError('sdvx.inのurlが不正です: ' + url)

		self.difficulty = {'n':'NOVICE',   'a':'ADVANCED', 'e':'EXHAUST',
		              'i':'INFINITE', 'g':'GRAVITY', 'm':'MAXIMUM'}[self._d]

		self.url['url']    = url

		self.url['bg']     = self.path + self.id + '/' + self.id + 'bg.png'
		self.url['bar']    = self.path + self.id + '/' + self.id + 'bar.png'
		self.url['jacket'] = self.path + self.id + '/' + self.id + self._d + '.jpg'
		self.url['data']   = self.path + 'obj/data' + self.id + self._d + '.png'

	def setHeader(self):
#		def ancestor(self,i):
#				if i == 0:
#						return self
#				else:
#						return ancestor(self.getparent(),i-1)

		source = self.getSource()
		root = lxml.html.fromstring(source)
		elements_div = root.xpath('//div')

		#set effector illustrator
#		element_searched = root.xpath('//div[text()="Effected by"]')[0]
#		element_effect = ancestor(element_searched, 5).getnext().xpath('.//div')[0]
		element_effect = elements_div[-2]
		effect = element_effect.text or ''
		illust = element_effect.text_content()[len(effect):]
		self.header['effect'] = effect
		self.header['illustrator'] = illust
		self.header['level'] = elements_div[3].text or ''
		self.header['title'] = elements_div[4].text or ''
		self.header['artist'] = (elements_div[-9].text or '')[3:]
		bpm = elements_div[-5].text or ''
		self.header['t'] = '' if '-' in bpm else bpm
		self.header['difficulty'] = {'n':'light', 'a':'challenge', 'e':'extended',
		                             'i':'infinite', 'g':'infinite', 'm':'maximum'}[self._d]
		self.header['jacket'] = 'jacket_%s.jpg' % self._d
		self.header['m'] = 'no' + ((';fx_%s.wav' % self._d)*4)[1:]

	def getHeader(self):
		if self.header == {}:
			self.setHeader()
		return '\r\n'.join(k + '=' + self.header[k] for k in self.header)

	def setCorrectUrl(self):
		source = self.getSource()
		root = lxml.html.fromstring(source)

		png = root.xpath('//p[@class="PNG"]')

		def correct_url(url):
			if url.startswith('//'):
				return 'https:' + url
			elif url.startswith('/'):
				return 'https://sdvx.in' + url
			elif url.startswith('http://') or url.startswith('https://'):
				return url
			return urllib.parse.urljoin(self.url['url'], url)

		if len(png) >= 3:
			bg, data, bar = [
				e.xpath('img')[0].attrib['src']
				for e in png[:3]
			]
			self.url['bg'] = correct_url(bg)
			self.url['data'] = correct_url(data)
			self.url['bar'] = correct_url(bar)
			return

		images = root.xpath('//img')
		png_images = []

		for img in images:
			src = img.attrib.get('src')
			if src and src.lower().endswith('.png'):
				png_images.append(src)

		if len(png_images) >= 3:
			self.url['bg'] = correct_url(png_images[0])
			self.url['data'] = correct_url(png_images[1])
			self.url['bar'] = correct_url(png_images[2])
			return

		raise ValueError('譜面画像のurlを取得できません')

	def setSource(self):
		print("webページを取得中")

		request = urllib.request.Request(
			self.url['url'],
			headers={
				'User-Agent': 'Mozilla/5.0'
			}
		)

		with urllib.request.urlopen(request) as response:
			self.source = response.read()

	def getSource(self):
		if 'source' not in dir(self):
			self.setSource()
		return self.source

#TODO レーン消え、アレンジ、等でbg,barの命名規則がカオス。殺す。
	def getImage(self, key):
		if key not in self.img:
			if self._d == 'g':
				try:#grv譜面は使いまわしされない画像かもしれない
					url = self.url[key]
					if key == 'bg':
						url = self.url['bg'][:-6] + 'gbg.png'
					elif key == 'bar':
						url = self.url['bar'][:-7] + 'gbar.png'
					imgdata = urllib.request.urlopen(url).read()
					self.img[key] = Image.open(BytesIO(imgdata))
					self.url[key] = url
				except HTTPError:
					url = self.url[key]
					imgdata = urllib.request.urlopen(url).read()
					self.img[key] = Image.open(BytesIO(imgdata))
			else:#レーンが消える背景はgbg.png
				try:
					url = self.url[key]
					imgdata = urllib.request.urlopen(url).read()
					self.img[key] = Image.open(BytesIO(imgdata))
				except HTTPError:
					if key == 'bg':
						self.url['bg'] = self.url['bg'][:-6] + 'gbg.png'
					else:
						raise HTTPError(str(key)+'のurlが不正です')
					url = self.url[key]
					imgdata = urllib.request.urlopen(url).read()
					self.img[key] = Image.open(BytesIO(imgdata))
		return self.img[key]

	def setYoutubeUrl(self):
		source = self.getSource()
		root = lxml.html.fromstring(source)
		ongen = root.xpath('//div[text()="音源"]')[0]
		while ongen.getnext() == None:
			ongen = ongen.getparent()
		fx = ongen.getnext()
		self.url['fx'] = fx.xpath(".//a")[0].attrib['href']
		nofx = fx.getnext()
		self.url['nofx'] = nofx.xpath(".//a")[0].attrib['href']

	def dl_music(self):
		def dl(url, filename):
			video = pafy.new(url)
			best = video.getbestaudio()
			nonwave_filename = filename + '.' + best.extension
			wave_filename = filename + '.wav'
			print('youtubeから' + best.title + 'をダウンロードしています')
			best.download(nonwave_filename)
			print(nonwave_filename + "の保存に成功しました")
			sound = AudioSegment.from_file(nonwave_filename)
			print(best.title + 'のwavファイルを生成しています')
			sound.export(wave_filename, format='wav')

		if 'fx' not in self.url or 'nofx' not in self.url:
			self.setYoutubeUrl()
		dl(self.url['fx'], 'fx_' + self._d)
		dl(self.url['nofx'], 'nofx_' + self._d)

	def getArray(self, key):
		if key not in self.arr:
			self.arr[key] = np.array(self.getImage(key).convert('RGBA'))
		return self.arr[key]

	def setSubscripts(self):
		bg =  self.getArray('bg')
		sample = bg[-1,:,3]
		i = np.where(sample != 0)[0][0]
		d = {12:70, 32:110}[i]
		x = []
		Y = []
		while True:
			try:
				sample = bg[:,i+8,0]
			except IndexError:
				break
			if not np.any(sample):
				break
			x.append(i)
			Y.append(np.where(sample == 204)[0])
			i+=d
		self.subscripts = [x, Y]

	def __getitem__(self, j):
		if 'subscripts' not in dir(self):
			self.setSubscripts()

		data = self.getArray('data')
		x, Y = self.subscripts

		for i, y in enumerate(Y):
			if j < len(y) - 1:
				return data[y[-2-j]:y[-1-j],x[i]:x[i]+55]
			else:
				j -= len(y) -1
		raise IndexError('Score index out of range')

	def __len__(self):
		if 'subscripts' not in dir(self):
			self.setSubscripts()
		return sum(len(i) - 1 for i in self.subscripts[1])

	def show(self):
		if 'self' not in self.img:
			bg   = self.getArray('bg').astype('float')
			data = self.getArray('data').astype('float')
			bar  = self.getArray('bar')
			tmp = (bg[:,:,:3]*bg[:,:,(3,3,3)]+data[:,:,:3]*data[:,:,(3,3,3)])/255
			mask = tmp > 256

			tmp = np.uint8(~mask*tmp + 255*mask)
			mask = bar[:,:,(3,3,3)] == 255
			tmp = ~mask*tmp + bar[:,:,:3]

			self.img['self'] = Image.fromarray(tmp)

		self.img['self'].show()

def isBTshort(arr):
	return np.all(arr == (254,255,252,255),axis=2)

#def isBTlong(sample):
#	white_l = (
#		(209,210,207,255),#灰
#
#		(226,148,191,255),#灰の上に赤
#		(220,174,200,255),
#		(234,125,191,255),
#		(209,201,206,255),
#
#		(152,168,224,255),#灰の上に青
#		(137,159,229,255),
#		(174,187,218,255),
#		(189,200,221,255),
#		(209,201,206,255)
#	)
#	return np.any(
#		np.c_[
#			tuple(
#				np.all(sample == w,axis=1)
#				for w in white_l
#			)
#		]
#	,axis=1)

def isBTlong(arr):
	x = arr[:,:,0]
	y = arr[:,:,1]
	z = arr[:,:,2]
	return -0.835*x -1.015*y + 483.48 < z
#	return 0.835*arr[:,:,0] + 1.015*arr[:,:,1] + arr[:,:,2] > 483.48

def parseBT(arr, mode):
	mode = int(mode)
	if arr.shape[0] % mode == 0:
		d = arr.shape[0]/mode
	else:
		raise Exception('画像を'+str(mode)+'分割できません')
	sample = arr[:,(12,22,32,42)][::-1][1::int(d)]
	s = isBTshort(sample)
	l = isBTlong(sample) & ~s
	return (2*l+s).astype('U1')

def isFXshort(sample):
	#yellow_s = ((255,148,27,255),(225,148,27,255))
	return sample[:,:,3] == 255

#def isFXlong(sample):
#	yellow_l = (
#		(255,159,7,107),#黄
#
#		(252,102,106,166),#黄の上に赤
#		(251,88,133,189),
#		(252,93,124,174),
#		(251,96,116,170),
#		(251,98,110,170),
#		(254,138,42,122),
#		(253,110,95,151),
#		(251,93,120,178),
#		(251,124,69,135),
#
#		(140,125,153,166),#黄の上に青
#		(115,123,187,189),
#		(128,125,171,176),
#		(122,123,178,182),
#		(136,126,160,169),
#		(200,147,76,128),
#		(155,137,135,154),
#		(132,124,165,172),
#		(238,153,31,114),
#		(176,141,109,141),
#		(143,129,153,164)
#	)
#	return np.any(
#		np.c_[
#			tuple(
#				np.all(sample == y,axis=1)
#				for y in yellow_l
#			)
#		]
#	,axis=1)
def isFXlong(arr):
	return (0.171104*arr[:,:,0] - 0.681597*arr[:,:,1] + arr[:,:,2] < 156.169) & \
	       ~np.all(arr == [0,0,0,0],axis=2)

def parseFX(arr, mode):
	mode = int(mode)
	if arr.shape[0] % mode == 0:
		d = arr.shape[0]/mode
	else:
		raise Exception('画像を'+str(mode)+'分割できません')

	sample = arr[:,(17,37)][::-1][1::int(d)]
	s = isFXshort(sample)
	l = isFXlong(sample) & ~s
	return (2*s+l).astype('U1')
	
def parseVOL(arr, mode):
	return np.array([['-','-']]*int(mode))

def parseMeasure(arr, mode):
	bt  = parseBT(arr, mode)
	fx  = parseFX(arr, mode)
	vol = parseVOL(arr, mode)
	v   = np.array(['|']*int(mode))
	return toStr(np.c_[bt,v,fx,v,vol])

def parseScore(score):
	h = '\r\n--\r\n'
	score = h.join([parseMeasure(k, int(k.shape[0]/2)) for k in score])
	return h + score + h

def adjustWave(fx_filename, nofx_filename):
	print("fx,nofx音源の位置合わせをしています")
	fps, fx = wf.read(fx_filename)
	fps2, nofx = wf.read(nofx_filename)

	d = 1
	fx_t = 20, 100
	nofx_t = fx_t[0] + d,  fx_t[1] - d
	if fps != fps2:
		print('fx音源とnofx音源のサンプリングレートが異なります')
		print('Audacityなどで音ズレを直して下さい')

	else:
		fxf = fx.astype('float32')
		nofxf = nofx.astype('float32')

		imag = fxf[ fps*fx_t[0] : fps*fx_t[1] ]
		templ = nofxf[ fps*nofx_t[0] : fps*nofx_t[1] ]
		res = cv2.matchTemplate(imag, templ, cv2.TM_SQDIFF)
		error = np.argmin(res) - d*fps
		print(str(error) + "フレームの音ズレを検出しました")
		if error == 0:
			pass
		elif error > 0:
			wf.write(fx_filename, fps, fx[error:])
		else:
			wf.write(nofx_filename, fps, nofx[-error:])


if __name__ == '__main__':
	if len(sys.argv) != 2:
		print('使い方:')
		print('python sdvx2ksh.py https://sdvx.in/05/05004m.htm')
		sys.exit(1)

	url = sys.argv[1]

	try:
		print('譜面を取得しています...')
		score = Score(url)

		print('ページを読み込んでいます...')
		score.getSource()

		print('譜面情報を取得しています...')
		score.setHeader()

		print('譜面画像を探しています...')
		score.setCorrectUrl()

		print('譜面画像を解析しています...')
		body = parseScore(score)

		filename = score.id + score._d + '.ksh'

		print('KSHファイルを書き込んでいます...')

		with codecs.open(filename, 'w', 'utf-8') as f:
			f.write(score.getHeader())
			f.write(body)

		print('')
		print('完了しました!')
		print('出力ファイル: ' + filename)

	except Exception as e:
		print('')
		print('エラーが発生しました:')
		print(str(e))
		sys.exit(1)
