#!/usr/bin/env python3
# coding:utf-8
import sys
import urllib.request
import urllib.parse
from urllib.error import HTTPError, URLError
import numpy as np
import lxml.html
from io import BytesIO
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

	### NEW:
	# sdvx.inのHTMLは時期によって構造が変わるため、
	# divの位置ではなく「ラベルの近くにある文字」を探す。
	#
	# 元コードでは elements_div[-2], elements_div[3],
	# elements_div[-9], elements_div[-5] などを使用していたが、
	# これはHTMLにdivが1つ増えただけでも list index out of range
	# になる。
	def setHeader(self):
		source = self.getSource()
		root = lxml.html.fromstring(source)

		# def ancestor(i):
		#
		# if i == 0:
		# 	return self
		# else:
		# 	return ancestor(self.getparent(),i-1)

		### NEW:
		# まずページ全体のテキストを行単位で取得する。
		lines = []
		for line in root.text_content().splitlines():
			line = re.sub(r'\s+', ' ', line).strip()
			if line:
				lines.append(line)

		full_text = '\n'.join(lines)

		### NEW:
		# 初期値を用意しておく。
		# 情報が見つからなくてもKSH生成自体は続行できるようにする。
		self.header['effect'] = ''
		self.header['illustrator'] = ''
		self.header['level'] = ''
		self.header['title'] = ''
		self.header['artist'] = ''
		self.header['t'] = ''

		# ---------------------------------------------------------------
		# title
		# ---------------------------------------------------------------

		### NEW:
		# HTMLの<title>は最後のフォールバックとして使用する。
		html_title = root.xpath('//title/text()')
		if html_title:
			self.header['title'] = html_title[0].strip()

		### NEW:
		# SDVXページでは曲名とアーティストが近接しているため、
		# 「/ ARTIST」の形式も検索する。
		for i, line in enumerate(lines):
			artist_match = re.match(r'^/\s*(.+)$', line)

			if artist_match:
				artist = artist_match.group(1).strip()

				if artist:
					self.header['artist'] = artist

				if i > 0 and not self.header['title']:
					self.header['title'] = lines[i - 1]

				break

		# ---------------------------------------------------------------
		# effect / illustrator
		# ---------------------------------------------------------------

		### NEW:
		# 元コードでは「Effected by」「Illustlated by」のHTML位置を
		# 仮定していた。
		#
		# 現在はラベルそのものを探し、その後ろのテキストを取得する。
		effect_patterns = [
			r'Effected\s*by\s*/?\s*(.+)',
			r'Effected\s*by[:：]?\s*(.+)',
			r'エフェクター[:：]?\s*(.+)',
		]

		for pattern in effect_patterns:
			match = re.search(
				pattern,
				full_text,
				re.I
			)

			if match:
				self.header['effect'] = match.group(1).strip()
				break

		illustrator_patterns = [
			r'Illust(?:l|r)ated\s*by\s*/?\s*(.+)',
			r'Illust(?:l|r)ated\s*by[:：]?\s*(.+)',
			r'イラスト[:：]?\s*(.+)',
		]

		for pattern in illustrator_patterns:
			match = re.search(
				pattern,
				full_text,
				re.I
			)

			if match:
				self.header['illustrator'] = match.group(1).strip()
				break

		# ---------------------------------------------------------------
		# level
		# ---------------------------------------------------------------

		### NEW:
		# difficulty名の近くからレベルを探す。
		difficulty_names = {
			'n': ['NOVICE', 'NOV'],
			'a': ['ADVANCED', 'ADV'],
			'e': ['EXHAUST', 'EXH'],
			'i': ['INFINITE', 'INF'],
			'g': ['GRAVITY', 'GRV'],
			'm': ['MAXIMUM', 'MXM'],
		}

		for i, line in enumerate(lines):
			if any(
				name.lower() in line.lower()
				for name in difficulty_names[self._d]
			):
				numbers = re.findall(r'\b\d{1,2}\b', line)

				if numbers:
					self.header['level'] = numbers[-1]
					break

				### NEW:
				# レベルが次の行にあるHTMLにも対応する。
				if i + 1 < len(lines):
					numbers = re.findall(
						r'\b\d{1,2}\b',
						lines[i + 1]
					)

					if numbers:
						self.header['level'] = numbers[-1]
						break

		# ---------------------------------------------------------------
		# BPM
		# ---------------------------------------------------------------

		### NEW:
		# 元コードの elements_div[-5] は廃止。
		bpm_patterns = [
			r'\bBPM\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?(?:\s*[-~]\s*[0-9]+(?:\.[0-9]+)?)?)',
			r'\bBPM\s+([0-9]+(?:\.[0-9]+)?)',
		]

		for pattern in bpm_patterns:
			match = re.search(
				pattern,
				full_text,
				re.I
			)

			if match:
				bpm = match.group(1).strip()

				# KSH側ではBPMが一定値でない場合、
				# 元コードと同じく空欄にする。
				if '-' not in bpm and '~' not in bpm:
					self.header['t'] = bpm

				break

		# ---------------------------------------------------------------
		# title cleanup
		# ---------------------------------------------------------------

		### NEW:
		# titleタグにはサイト名などが付いている場合があるので、
		# 明らかにページタイトルでない場合はそのまま使う。
		self.header['title'] = re.sub(
			r'\s+',
			' ',
			self.header['title']
		).strip()

		# ---------------------------------------------------------------
		# KSH-specific values
		# ---------------------------------------------------------------

		self.header['difficulty'] = {
			'n':'light',
			'a':'challenge',
			'e':'extended',
			'i':'infinite',
			'g':'infinite',
			'm':'maximum'
		}[self._d]

		self.header['jacket'] = 'jacket_%s.jpg' % self._d
		self.header['m'] = 'no' + ((';fx_%s.wav' % self._d)*4)[1:]

	def getHeader(self):
		if self.header == {}:
			self.setHeader()
		return '\r\n'.join(k + '=' + self.header[k] for k in self.header)

	def setCorrectUrl(self):
		source = self.getSource()
		root = lxml.html.fromstring(source)

		def correct_url(url):
			if not url:
				return None

			url = url.strip()

			if url.startswith('//'):
				return 'https:' + url
			elif url.startswith('/'):
				return 'https://sdvx.in' + url
			elif url.startswith('http://') or url.startswith('https://'):
				return url

			return urllib.parse.urljoin(self.url['url'], url)
		### NEW:
		# デバッグ用:
		# 実際にどの画像URLを使用しているか表示する。
		print('')
		print('検出した譜面画像URL:')
		print('  bg   = ' + self.url['bg'])
		print('  data = ' + self.url['data'])
		print('  bar  = ' + self.url['bar'])
		print('')

		### NEW:
		# sdvx.inの譜面ページには、譜面確認用のPNG画像が
		# 複数の <p class="PNG"> ブロックとして配置されている。
		#
		# 元コード:
		#
		#     png = root.xpath('//p[@class="PNG"]')
		#
		# ではclass属性が完全一致する必要がある。
		#
		# 現在のHTMLではclass属性に別のclassが追加される可能性が
		# あるため、class名としてPNGを含むものを検索する。
		png = root.xpath(
			'//p[contains(concat(" ", normalize-space(@class), " "), " PNG ")]'
		)

		candidates = []

		for e in png:
			imgs = e.xpath('.//img')

			for img in imgs:
				src = img.attrib.get('src')

				if not src:
					continue

				url = correct_url(src)

				if url and url not in candidates:
					candidates.append(url)

		### NEW:
		# まず、HTMLに明示されたPNGだけを使う。
		#
		# 「ページ内の最初の3枚のPNG」を使うとfaviconや
		# その他の画像を誤って譜面画像として扱う可能性がある。
		if len(candidates) >= 3:

			# 元プロジェクトの期待する順番:
			#
			# bg -> data -> bar
			#
			# を維持する。
			self.url['bg'] = candidates[0]
			self.url['data'] = candidates[1]
			self.url['bar'] = candidates[2]

			return

		### NEW:
		# PNGクラスが取得できない場合のフォールバック。
		#
		# ただし、ここでも「最初の3枚」を無条件に使わず、
		# 画像の実体をHEAD/GETしてサイズを確認する。
		images = root.xpath('//img')

		png_images = []

		for img in images:
			src = img.attrib.get('src')

			if not src:
				continue

			if not re.search(r'\.png(?:\?.*)?$', src, re.I):
				continue

			url = correct_url(src)

			if url and url not in png_images:
				png_images.append(url)

		### NEW:
		# 実際に画像として読み込めるPNGだけを残す。
		valid_images = []

		for url in png_images:
			try:
				request = urllib.request.Request(
					url,
					headers={
						'User-Agent': 'Mozilla/5.0',
						'Referer': self.url['url'],
					}
				)

				with urllib.request.urlopen(
					request,
					timeout=15
				) as response:
					data = response.read()

				image = Image.open(BytesIO(data))

				# 小さいアイコン等を除外する。
				if image.width >= 50 and image.height >= 50:
					valid_images.append(url)

			except Exception:
				continue

		if len(valid_images) >= 3:
			self.url['bg'] = valid_images[0]
			self.url['data'] = valid_images[1]
			self.url['bar'] = valid_images[2]
			return

		### NEW:
		# 最後に、元リポジトリの命名規則を試す。
		#
		# これは古いページ用のフォールバック。
		# ここでURLを設定するだけにして、実際の404は
		# getImage()側で分かりやすく報告する。
		self.url['bg'] = urllib.parse.urljoin(
			self.url['url'],
			self.id + '/' + self.id + 'bg.png'
		)

		self.url['bar'] = urllib.parse.urljoin(
			self.url['url'],
			self.id + '/' + self.id + 'bar.png'
		)

		self.url['data'] = urllib.parse.urljoin(
			self.url['url'],
			'obj/data' + self.id + self._d + '.png'
		)

		def correct_url(url):
			### NEW:
			# 空URLにも明示的なエラーを出す。
			if not url:
				raise ValueError('空の画像urlです')

			if url.startswith('//'):
				return 'https:' + url
			elif url.startswith('/'):
				return 'https://sdvx.in' + url
			elif url.startswith('http://') or url.startswith('https://'):
				return url
			return urllib.parse.urljoin(self.url['url'], url)

		if len(png) >= 3:
			images = []

			for e in png:
				imgs = e.xpath('.//img')

				if not imgs:
					continue

				src = imgs[0].attrib.get('src')

				if src:
					images.append(correct_url(src))

			if len(images) >= 3:
				self.url['bg'] = images[0]
				self.url['data'] = images[1]
				self.url['bar'] = images[2]
				return

		### NEW:
		# class=PNG が存在しない場合のフォールバック。
		# ただしfaviconやアイコンなどのPNGが混ざる可能性があるため、
		# 画像サイズを後で検証する。
		images = root.xpath('//img')
		png_images = []

		for img in images:
			src = img.attrib.get('src')

			if not src:
				continue

			if re.search(r'\.png(?:\?.*)?$', src, re.I):
				png_images.append(correct_url(src))

		if len(png_images) >= 3:
			self.url['bg'] = png_images[0]
			self.url['data'] = png_images[1]
			self.url['bar'] = png_images[2]
			return

		### NEW:
		# HTMLから画像が取れなかった場合は、
		# 元々のsdvx.in命名規則を最後のフォールバックとして使う。
		self.url['bg'] = urllib.parse.urljoin(
			self.url['url'],
			self.id + '/' + self.id + 'bg.png'
		)

		self.url['bar'] = urllib.parse.urljoin(
			self.url['url'],
			self.id + '/' + self.id + 'bar.png'
		)

		self.url['data'] = urllib.parse.urljoin(
			self.url['url'],
			'obj/data' + self.id + self._d + '.png'
		)

		### NEW:
		# URL自体は作れたのでここでは終了。
		# 実際に存在するかどうかは getImage() で検証する。
		return

	def setSource(self):
		print("webページを取得中")

		request = urllib.request.Request(
			self.url['url'],
			headers={
				'User-Agent': (
					'Mozilla/5.0 '
					'(Windows NT 10.0; Win64; x64) '
					'AppleWebKit/537.36 '
					'(KHTML, like Gecko) '
					'Chrome/131.0 Safari/537.36'
				),
				'Accept': (
					'text/html,application/xhtml+xml,'
					'application/xml;q=0.9,*/*;q=0.8'
				),
				'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
				'Referer': 'https://sdvx.in/',
			}
		)

		try:
			with urllib.request.urlopen(request, timeout=30) as response:
				self.source = response.read()

		except HTTPError as e:
			raise RuntimeError(
				'webページを取得できませんでした: HTTP ' +
				str(e.code)
			)

		except URLError as e:
			raise RuntimeError(
				'webページを取得できませんでした: ' +
				str(e.reason)
			)

	def getSource(self):
		if 'source' not in dir(self):
			self.setSource()
		return self.source

#TODO レーン消え、アレンジ、等でbg,barの命名規則がカオス。殺す。
	def getImage(self, key):
		if key not in self.img:

			### NEW:
			# 画像をダウンロードする共通処理。
			# sdvx.in側の画像URLはページによって異なるため、
			# URLを試すたびにUser-AgentとRefererを付ける。
			def download_image(url):
				request = urllib.request.Request(
					url,
					headers={
						'User-Agent': (
							'Mozilla/5.0 '
							'(Windows NT 10.0; Win64; x64) '
							'AppleWebKit/537.36 '
							'(KHTML, like Gecko) '
							'Chrome/131.0 Safari/537.36'
						),
						'Referer': self.url['url'],
					}
				)

				try:
					with urllib.request.urlopen(
						request,
						timeout=30
					) as response:
						imgdata = response.read()

					return Image.open(
						BytesIO(imgdata)
					).convert('RGBA')

				except HTTPError as e:
					raise RuntimeError(
						key + '画像を取得できませんでした: ' +
						url +
						' (HTTP ' + str(e.code) + ')'
					)

				except Exception as e:
					raise RuntimeError(
						key + '画像を読み込めませんでした: ' +
						url +
						' (' + str(e) + ')'
					)

			### NEW:
			# まずsetCorrectUrl()で見つけたURLをそのまま試す。
			#
			# 重要:
			# ここではbg.pngをgbg.pngへ勝手に変更しない。
			# 現在のsdvx.inではgbg.pngが存在しない譜面もある。
			url = self.url[key]

			try:
				self.img[key] = download_image(url)
				return self.img[key]

			except RuntimeError as original_error:

				### NEW:
				# 元コードでは「bgが404ならgbg.png」を試していた。
				#
				# これは古いsdvx.inの命名規則を前提としているため、
				# 現在のページでは逆に404を発生させる原因になる。
				#
				# そのため、gbg.pngへの変換は廃止する。
				#
				# Gravity譜面についても同様に、HTMLから取得した
				# URLを最優先する。

				raise original_error
		print('譜面画像を解析しています...')
		print('bg URL   : ' + score.url['bg'])
		print('data URL : ' + score.url['data'])
		print('bar URL  : ' + score.url['bar'])
		body = parseScore(score)

		return self.img[key]

	def setYoutubeUrl(self):
		source = self.getSource()
		root = lxml.html.fromstring(source)

		### NEW:
		# 音源ブロックが存在しないページでも
		# IndexError ではなく明示的なエラーを出す。
		ongen_list = root.xpath('//div[normalize-space(text())="音源"]')

		if not ongen_list:
			raise ValueError('音源情報がページにありません')

		ongen = ongen_list[0]

		while ongen.getnext() is None:
			parent = ongen.getparent()

			if parent is None:
				raise ValueError('音源情報の構造を解析できません')

			ongen = parent

		fx = ongen.getnext()
		fx_links = fx.xpath(".//a")

		if not fx_links:
			raise ValueError('FX音源のURLを取得できません')

		self.url['fx'] = fx_links[0].attrib['href']

		nofx = fx.getnext()

		if nofx is None:
			raise ValueError('NOFX音源の情報を取得できません')

		nofx_links = nofx.xpath(".//a")

		if not nofx_links:
			raise ValueError('NOFX音源のURLを取得できません')

		self.url['nofx'] = nofx_links[0].attrib['href']

	def dl_music(self):
		print('音源のダウンロードは現在サポートしていません')

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

		### NEW:
		# 元コードでは np.where(...)[0][0] を直接参照していたため、
		# 背景画像の形式が変わるとここでも IndexError になる。
		sample = bg[-1,:,3]
		nonzero = np.where(sample != 0)[0]

		if len(nonzero) == 0:
			raise ValueError(
				'BG画像から譜面レーンの開始位置を検出できません'
			)

		i = nonzero[0]

		### NEW:
		# 元コードは12/32の2種類だけを許容していた。
		# 現在の画像でもこの2種類を優先するが、
		# それ以外の場合は画像からレーン間隔を推定する。
		if i in {12, 32}:
			d = {12:70, 32:110}[i]
		else:
			# 元形式に近い候補を調べる。
			# BG画像の下端に繰り返し現れる非透明領域から推定する。
			candidates = [70, 110]

			best_d = None
			best_score = -1

			for candidate in candidates:
				score = 0
				test_i = i

				while test_i + 8 < bg.shape[1]:
					s = bg[:,test_i+8,0]

					if not np.any(s):
						break

					score += 1
					test_i += candidate

				if score > best_score:
					best_score = score
					best_d = candidate

			d = best_d if best_d is not None else 70

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

		### NEW:
		# 少なくとも1小節分の境界が必要。
		if not Y or not any(len(y) >= 2 for y in Y):
			raise ValueError(
				'BG画像から小節境界を検出できません'
			)

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

			tmp = (
				bg[:,:,:3]*bg[:,:,(3,3,3)] +
				data[:,:,:3]*data[:,:,(3,3,3)]
			) / 255

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

	if mode <= 0:
		raise ValueError('BT解析の分割数が0以下です')

	if arr.shape[0] % mode == 0:
		d = arr.shape[0]/mode
	else:
		### NEW:
		# 元コードと同じ条件を維持する。
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

	if mode <= 0:
		raise ValueError('FX解析の分割数が0以下です')

	if arr.shape[0] % mode == 0:
		d = arr.shape[0]/mode
	else:
		raise Exception('画像を'+str(mode)+'分割できません')

	sample = arr[:,(17,37)][::-1][1::int(d)]
	s = isFXshort(sample)
	l = isFXlong(sample) & ~s

	return (2*s+l).astype('U1')


def parseVOL(arr, mode):
	### NEW:
	# 元コードではVOLを常に空にしていた。
	#
	# ここでは意図的に元の動作を維持する。
	# VOL画像の正確な色・形状を確認せず推測してしまうと、
	# レーザーが大量に誤変換される可能性がある。
	#
	# TODO:
	# sdvx.inのdata PNGを解析してVOLの始点・終点・曲線を
	# KSHのVOL形式へ変換する。
	return np.array([['-','-']]*int(mode))


def parseMeasure(arr, mode):
	bt  = parseBT(arr, mode)
	fx  = parseFX(arr, mode)
	vol = parseVOL(arr, mode)
	v   = np.array(['|']*int(mode))

	return toStr(np.c_[bt,v,fx,v,vol])


def parseScore(score):
	h = '\r\n--\r\n'

	### NEW:
	# 元コードの
	#
	#     int(k.shape[0]/2)
	#
	# をそのまま使用する。
	#
	# これは元プロジェクトの画像解析方法と対応しているため、
	# ここを勝手に変更するとBT/FXのタイミングが変わる。
	score = h.join([
		parseMeasure(k, int(k.shape[0]/2))
		for k in score
	])

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

		res = cv2.matchTemplate(
			imag,
			templ,
			cv2.TM_SQDIFF
		)

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
