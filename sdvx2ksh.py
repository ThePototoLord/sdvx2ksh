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

		self.difficulty = {
			'n':'NOVICE',
			'a':'ADVANCED',
			'e':'EXHAUST',
			'i':'INFINITE',
			'g':'GRAVITY',
			'm':'MAXIMUM'
		}[self._d]

		self.url['url']    = url

		self.url['bg']     = self.path + self.id + '/' + self.id + 'bg.png'
		self.url['bar']    = self.path + self.id + '/' + self.id + 'bar.png'
		self.url['jacket'] = self.path + self.id + '/' + self.id + self._d + '.jpg'
		self.url['data']   = self.path + 'obj/data' + self.id + self._d + '.png'

	### NEW:
	# URLに対してHTTP GETを行い、画像として読み込めるか確認する。
	# setCorrectUrl()で実際に存在する画像を探すために使用する。
	def _download_image(self, url):
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
				'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
			}
		)

		with urllib.request.urlopen(request, timeout=30) as response:
			imgdata = response.read()

		image = Image.open(BytesIO(imgdata))
		image.load()

		return image.convert('RGBA')

	def setHeader(self):
		source = self.getSource()
		root = lxml.html.fromstring(source)

		# def ancestor(self,i):
		#
		# if i == 0:
		#
		# return self
		#
		# else:
		#
		# return ancestor(self.getparent(),i-1)

		### NEW:
		# 元コードではHTML内のdivの絶対位置を使用していた。
		#
		#     elements_div[-2]
		#     elements_div[3]
		#     elements_div[4]
		#     elements_div[-9]
		#     elements_div[-5]
		#
		# という方式は、ページのdivが1つ増減しただけで
		# list index out of rangeになる。
		#
		# 現在はページ全体のテキストから情報を探し、
		# 見つからない項目は空文字列にする。

		lines = []

		for line in root.text_content().splitlines():
			line = re.sub(r'\s+', ' ', line).strip()

			if line:
				lines.append(line)

		full_text = '\n'.join(lines)

		self.header['effect'] = ''
		self.header['illustrator'] = ''
		self.header['level'] = ''
		self.header['title'] = ''
		self.header['artist'] = ''
		self.header['t'] = ''

		#set effector illustrator
		#
		# element_searched = root.xpath('//div[text()="Effected by"]')[0]
		# element_effect = ancestor(element_searched, 5).getnext().xpath('.//div')[0]

		### NEW:
		# Effected by / Illustrator のラベルをHTMLの位置ではなく
		# テキストから検索する。
		effect_patterns = [
			r'Effected\s*by\s*/?\s*(.+)',
			r'Effected\s*by\s*[:：]?\s*(.+)',
			r'エフェクター\s*[:：]?\s*(.+)',
		]

		for pattern in effect_patterns:
			match = re.search(pattern, full_text, re.I)

			if match:
				self.header['effect'] = match.group(1).strip()
				break

		illustrator_patterns = [
			r'Illustrated\s*by\s*/?\s*(.+)',
			r'Illustlated\s*by\s*/?\s*(.+)',
			r'Illustrated\s*by\s*[:：]?\s*(.+)',
			r'Illustlated\s*by\s*[:：]?\s*(.+)',
			r'イラスト\s*[:：]?\s*(.+)',
		]

		for pattern in illustrator_patterns:
			match = re.search(pattern, full_text, re.I)

			if match:
				self.header['illustrator'] = match.group(1).strip()
				break

		### NEW:
		# titleタグを最初のフォールバックとして使う。
		title_elements = root.xpath('//title/text()')

		if title_elements:
			self.header['title'] = re.sub(
				r'\s+',
				' ',
				title_elements[0]
			).strip()

		### NEW:
		# ページ内に「/ artist」のような表記がある場合に使用する。
		for i, line in enumerate(lines):
			match = re.match(r'^/\s*(.+)$', line)

			if match:
				self.header['artist'] = match.group(1).strip()

				if i > 0 and not self.header['title']:
					self.header['title'] = lines[i-1]

				break

		### NEW:
		# difficulty名の近くにある数値をlevelとして使用する。
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

				if i + 1 < len(lines):
					numbers = re.findall(
						r'\b\d{1,2}\b',
						lines[i+1]
					)

					if numbers:
						self.header['level'] = numbers[-1]
						break

		### NEW:
		# BPMもdivの位置ではなくラベルから取得する。
		bpm_patterns = [
			r'\bBPM\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?(?:\s*[-~]\s*[0-9]+(?:\.[0-9]+)?)?)',
			r'\bBPM\s+([0-9]+(?:\.[0-9]+)?)',
		]

		for pattern in bpm_patterns:
			match = re.search(pattern, full_text, re.I)

			if match:
				bpm = match.group(1).strip()

				self.header['t'] = (
					''
					if '-' in bpm or '~' in bpm
					else bpm
				)

				break

		### NEW:
		# titleが空の場合はページ内の比較的長いテキストを
		# フォールバックとして探す。
		if not self.header['title']:
			for line in lines:
				if (
					len(line) >= 2 and
					len(line) <= 200 and
					not re.search(
						r'BPM|Effected|Illustrated|Artist|NOVICE|ADVANCED|EXHAUST|INFINITE|GRAVITY|MAXIMUM',
						line,
						re.I
					)
				):
					self.header['title'] = line
					break

		self.header['difficulty'] = {
			'n':'light',
			'a':'challenge',
			'e':'extended',
			'i':'infinite',
			'g':'infinite',
			'm':'maximum'
		}[self._d]

		self.header['jacket'] = 'jacket_%s.jpg' % self._d

		self.header['m'] = 'no' + (
			(';fx_%s.wav' % self._d) * 4
		)[1:]

	def getHeader(self):
		if self.header == {}:
			self.setHeader()

		return '\r\n'.join(
			k + '=' + self.header[k]
			for k in self.header
		)

	def setCorrectUrl(self):
		source = self.getSource()
		root = lxml.html.fromstring(source)

		### NEW:
		# 現在のsdvx.inでは古い画像命名規則が常に存在するとは
		# 限らない。
		#
		# そのため、まずHTMLに書かれているimg srcをすべて調べ、
		# 実際にダウンロードできる画像だけを候補にする。

		def correct_url(url):
			if not url:
				return None

			url = url.strip()

			if url.startswith('//'):
				return 'https:' + url

			elif url.startswith('/'):
				return 'https://sdvx.in' + url

			elif (
				url.startswith('http://') or
				url.startswith('https://')
			):
				return url

			return urllib.parse.urljoin(
				self.url['url'],
				url
			)

		### NEW:
		# HTML内のすべてのimg要素を調べる。
		images = root.xpath('//img')

		candidates = []

		for img in images:
			src = img.attrib.get('src')

			if not src:
				continue

			url = correct_url(src)

			if not url:
				continue

			if url in [c['url'] for c in candidates]:
				continue

			### NEW:
			# img自身だけでなく親要素のテキストも保存する。
			# 「譜面」「data」「bar」などのラベルが近くにある
			# HTMLではこれを利用して役割を判定できる。
			parent_text = ''

			parent = img.getparent()

			if parent is not None:
				parent_text = parent.text_content()

				grandparent = parent.getparent()

				if grandparent is not None:
					parent_text += ' ' + grandparent.text_content()

			candidates.append({
				'url': url,
				'src': src,
				'text': re.sub(
					r'\s+',
					' ',
					parent_text
				).strip(),
			})

		### NEW:
		# p class="PNG" の画像は優先候補にする。
		png = root.xpath(
			'//p[contains(concat(" ", normalize-space(@class), " "), " PNG ")]'
		)

		png_urls = set()

		for element in png:
			for img in element.xpath('.//img'):
				src = img.attrib.get('src')

				if src:
					url = correct_url(src)

					if url:
						png_urls.add(url)

		### NEW:
		# 各候補を実際に取得して画像サイズを調べる。
		# 404等はここで除外する。
		valid_images = []

		for candidate in candidates:
			url = candidate['url']

			try:
				image = self._download_image(url)

				width, height = image.size

				if width < 100 or height < 100:
					continue

				candidate['width'] = width
				candidate['height'] = height
				candidate['image'] = image
				candidate['is_png_block'] = url in png_urls

				valid_images.append(candidate)

			except Exception:
				### NEW:
				# 404や壊れた画像は候補から除外する。
				continue

		### NEW:
		# デバッグ用:
		# 実際に取得できた画像をすべて表示する。
		print('')
		print('取得可能な画像:')

		for candidate in valid_images:
			print(
				'  %dx%d  %s'
				% (
					candidate['width'],
					candidate['height'],
					candidate['url']
				)
			)

		print('')

		if not valid_images:
			raise ValueError(
				'sdvx.inから取得可能な譜面画像が見つかりません'
			)

		### NEW:
		# 画像の役割を判定する。
		#
		# ファイル名だけに依存せず、
		# URL、HTMLの周辺テキスト、PNGブロック、画像サイズを
		# 組み合わせてスコアリングする。

		def score_candidate(candidate, role):
			url_lower = candidate['url'].lower()
			text_lower = candidate['text'].lower()

			score = 0

			if candidate.get('is_png_block'):
				score += 20

			filename = url_lower.rsplit('/', 1)[-1]

			if role == 'data':
				if 'data' in filename:
					score += 100

				if '/obj/' in url_lower:
					score += 80

				if 'data' in text_lower:
					score += 40

			elif role == 'bg':
				if 'gbg' in filename:
					score += 60

				if re.search(r'(^|[^a-z])bg([^a-z]|$)', filename):
					score += 80

				if 'background' in text_lower:
					score += 40

				### NEW:
				# data画像は通常obj/dataという場所にあるので
				# bg候補から減点する。
				if '/obj/' in url_lower:
					score -= 80

			elif role == 'bar':
				if 'gbar' in filename:
					score += 60

				if re.search(r'(^|[^a-z])bar([^a-z]|$)', filename):
					score += 80

				if 'bar' in text_lower:
					score += 40

				if '/obj/' in url_lower:
					score -= 50

			### NEW:
			# 同じページIDを含む画像を少し優先する。
			if self.id.lower() in filename:
				score += 10

			return score

		### NEW:
		# まずdataを特定する。
		data_sorted = sorted(
			valid_images,
			key=lambda x: score_candidate(x, 'data'),
			reverse=True
		)

		### NEW:
		# 明らかにdata画像として認識できる場合のみ採用する。
		if data_sorted:
			data_candidate = data_sorted[0]

			if score_candidate(data_candidate, 'data') > 0:
				self.url['data'] = data_candidate['url']
			else:
				data_candidate = None
		else:
			data_candidate = None

		### NEW:
		# dataとして使った画像はbg/bar候補から除外する。
		remaining = [
			candidate
			for candidate in valid_images
			if candidate is not data_candidate
		]

		bg_sorted = sorted(
			remaining,
			key=lambda x: score_candidate(x, 'bg'),
			reverse=True
		)

		bar_sorted = sorted(
			remaining,
			key=lambda x: score_candidate(x, 'bar'),
			reverse=True
		)

		### NEW:
		# bg候補。
		bg_candidate = None

		if bg_sorted:
			candidate = bg_sorted[0]

			if score_candidate(candidate, 'bg') > 0:
				bg_candidate = candidate

		### NEW:
		# bar候補。
		bar_candidate = None

		for candidate in bar_sorted:
			if candidate is bg_candidate:
				continue

			if score_candidate(candidate, 'bar') > 0:
				bar_candidate = candidate
				break

		### NEW:
		# 旧命名規則の画像が存在する場合は、
		# 明示的に優先する。
		#
		# ただし存在しないURLを作ってはいけない。
		if bg_candidate is None:
			for candidate in remaining:
				filename = candidate['url'].lower().rsplit('/', 1)[-1]

				if (
					filename == self.id.lower() + 'bg.png' or
					filename == self.id.lower() + 'gbg.png'
				):
					bg_candidate = candidate
					break

		if bar_candidate is None:
			for candidate in remaining:
				if candidate is bg_candidate:
					continue

				filename = candidate['url'].lower().rsplit('/', 1)[-1]

				if (
					filename == self.id.lower() + 'bar.png' or
					filename == self.id.lower() + 'gbar.png'
				):
					bar_candidate = candidate
					break

		### NEW:
		# dataはこのリポジトリの元仕様に従っている可能性が高いので、
		# HTMLで見つからない場合のみ既定URLを候補として追加する。
		#
		# ここでもURLを実際に取得して確認する。
		if data_candidate is None:
			default_data = (
				self.path +
				'obj/data' +
				self.id +
				self._d +
				'.png'
			)

			try:
				image = self._download_image(default_data)

				if image.width >= 100 and image.height >= 100:
					self.url['data'] = default_data
					data_candidate = {
						'url': default_data,
						'width': image.width,
						'height': image.height,
						'image': image,
					}

			except Exception:
				pass

		### NEW:
		# 必要な画像が全部特定できなければ、
		# 「推測したURL」で続行せず候補一覧を表示して停止する。
		if data_candidate is None:
			raise ValueError(
				'譜面data画像を特定できませんでした'
			)

		if bg_candidate is None:
			raise ValueError(
				'譜面背景画像(bg)を特定できませんでした'
			)

		if bar_candidate is None:
			raise ValueError(
				'譜面bar画像(bar)を特定できませんでした'
			)

		self.url['bg'] = bg_candidate['url']
		self.url['bar'] = bar_candidate['url']

		print('使用する譜面画像URL:')
		print('  bg   = ' + self.url['bg'])
		print('  data = ' + self.url['data'])
		print('  bar  = ' + self.url['bar'])
		print('')

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
			with urllib.request.urlopen(
				request,
				timeout=30
			) as response:
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
			# setCorrectUrl()で既に検証済みのURLを使用する。
			# ここではbg.png -> gbg.pngのような推測をしない。
			#
			# 元コード:
			#
			# if self._d == 'g':
			#     ...
			#
			# ではGravity譜面の場合にgbg/gbarへ強制変換していたが、
			# 現在のsdvx.inでは存在しない場合がある。
			url = self.url[key]

			try:
				self.img[key] = self._download_image(url)

			except HTTPError as e:
				raise RuntimeError(
					key +
					'画像を取得できませんでした: ' +
					url +
					' (HTTP ' +
					str(e.code) +
					')'
				)

			except Exception as e:
				raise RuntimeError(
					key +
					'画像を読み込めませんでした: ' +
					url +
					' (' +
					str(e) +
					')'
				)

		return self.img[key]

	def setYoutubeUrl(self):
		source = self.getSource()
		root = lxml.html.fromstring(source)

		### NEW:
		# 元コードは必ず[0]を取得していたため、
		# 音源ブロックがないページではIndexErrorになる。
		ongen_list = root.xpath(
			'//div[normalize-space(text())="音源"]'
		)

		if not ongen_list:
			raise ValueError('音源情報がページにありません')

		ongen = ongen_list[0]

		while ongen.getnext() is None:
			parent = ongen.getparent()

			if parent is None:
				raise ValueError(
					'音源情報の構造を解析できません'
				)

			ongen = parent

		fx = ongen.getnext()
		fx_links = fx.xpath('.//a')

		if not fx_links:
			raise ValueError(
				'FX音源のURLを取得できません'
			)

		self.url['fx'] = fx_links[0].attrib['href']

		nofx = fx.getnext()

		if nofx is None:
			raise ValueError(
				'NOFX音源の情報を取得できません'
			)

		nofx_links = nofx.xpath('.//a')

		if not nofx_links:
			raise ValueError(
				'NOFX音源のURLを取得できません'
			)

		self.url['nofx'] = nofx_links[0].attrib['href']

	def dl_music(self):
		print('音源のダウンロードは現在サポートしていません')

		if 'fx' not in self.url or 'nofx' not in self.url:
			self.setYoutubeUrl()

		dl(self.url['fx'], 'fx_' + self._d)
		dl(self.url['nofx'], 'nofx_' + self._d)

	def getArray(self, key):
		if key not in self.arr:
			self.arr[key] = np.array(
				self.getImage(key).convert('RGBA')
			)

		return self.arr[key]

	def setSubscripts(self):
		bg = self.getArray('bg')

		### NEW:
		# 元コードではnp.where(...)[0][0]を直接参照していた。
		# 画像形式が違う場合はIndexErrorになるため、
		# まず候補が存在するか確認する。
		sample = bg[-1,:,3]
		nonzero = np.where(sample != 0)[0]

		if len(nonzero) == 0:
			raise ValueError(
				'BG画像から譜面レーンの開始位置を検出できません'
			)

		i = nonzero[0]

		### NEW:
		# 元コードの12/32の2種類をそのまま優先する。
		if i in {12, 32}:
			d = {12:70, 32:110}[i]

		else:
			### NEW:
			# それ以外の画像形式では、元コードで使われていた
			# 70/110を候補として簡易的に評価する。
			candidates = [70, 110]

			best_d = candidates[0]
			best_score = -1

			for candidate_d in candidates:
				score = 0
				test_i = i

				while test_i + 8 < bg.shape[1]:
					try:
						s = bg[:,test_i+8,0]
					except IndexError:
						break

					if not np.any(s):
						break

					score += 1
					test_i += candidate_d

				if score > best_score:
					best_score = score
					best_d = candidate_d

			d = best_d

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
		# 小節境界が見つからない場合は明示的に停止する。
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
				return data[
					y[-2-j]:y[-1-j],
					x[i]:x[i]+55
				]
			else:
				j -= len(y) - 1

		raise IndexError('Score index out of range')

	def __len__(self):
		if 'subscripts' not in dir(self):
			self.setSubscripts()

		return sum(
			len(i) - 1
			for i in self.subscripts[1]
		)

	def show(self):
		if 'self' not in self.img:
			bg   = self.getArray('bg').astype('float')
			data = self.getArray('data').astype('float')
			bar  = self.getArray('bar')

			tmp = (
				bg[:,:,:3] *
				bg[:,:,(3,3,3)] +
				data[:,:,:3] *
				data[:,:,(3,3,3)]
			) / 255

			mask = tmp > 256

			tmp = np.uint8(
				~mask * tmp +
				255 * mask
			)

			mask = bar[:,:,(3,3,3)] == 255

			tmp = ~mask * tmp + bar[:,:,:3]

			self.img['self'] = Image.fromarray(tmp)

		self.img['self'].show()


def isBTshort(arr):
	return np.all(
		arr == (254,255,252,255),
		axis=2
	)


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
		raise ValueError(
			'BT解析の分割数が0以下です'
		)

	if arr.shape[0] % mode == 0:
		d = arr.shape[0]/mode
	else:
		raise Exception(
			'画像を'+str(mode)+'分割できません'
		)

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
	return (
		0.171104*arr[:,:,0] -
		0.681597*arr[:,:,1] +
		arr[:,:,2] < 156.169
	) & ~np.all(
		arr == [0,0,0,0],
		axis=2
	)

def parseFX(arr, mode):
	mode = int(mode)

	if mode <= 0:
		raise ValueError(
			'FX解析の分割数が0以下です'
		)

	if arr.shape[0] % mode == 0:
		d = arr.shape[0]/mode
	else:
		raise Exception(
			'画像を'+str(mode)+'分割できません'
		)

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
	return np.array(
		[['-','-']]*int(mode)
	)


def parseMeasure(arr, mode):
	bt  = parseBT(arr, mode)
	fx  = parseFX(arr, mode)
	vol = parseVOL(arr, mode)
	v   = np.array(['|']*int(mode))

	return toStr(
		np.c_[
			bt,
			v,
			fx,
			v,
			vol
		]
	)


def parseScore(score):
	h = '\r\n--\r\n'

	### NEW:
	# 元コードの画像→小節→KSH変換方法を維持する。
	score = h.join(
		[
			parseMeasure(
				k,
				int(k.shape[0]/2)
			)
			for k in score
		]
	)

	return h + score + h


def adjustWave(fx_filename, nofx_filename):
	print("fx,nofx音源の位置合わせをしています")
	fps, fx = wf.read(fx_filename)
	fps2, nofx = wf.read(nofx_filename)

	d = 1
	fx_t = 20, 100
	nofx_t = fx_t[0] + d, fx_t[1] - d

	if fps != fps2:
		print(
			'fx音源とnofx音源のサンプリングレートが異なります'
		)

		print(
			'Audacityなどで音ズレを直して下さい'
		)

	else:
		fxf = fx.astype('float32')
		nofxf = nofx.astype('float32')

		imag = fxf[
			fps*fx_t[0] :
			fps*fx_t[1]
		]

		templ = nofxf[
			fps*nofx_t[0] :
			fps*nofx_t[1]
		]

		res = cv2.matchTemplate(
			imag,
			templ,
			cv2.TM_SQDIFF
		)

		error = np.argmin(res) - d*fps

		print(
			str(error) +
			"フレームの音ズレを検出しました"
		)

		if error == 0:
			pass

		elif error > 0:
			wf.write(
				fx_filename,
				fps,
				fx[error:]
			)

		else:
			wf.write(
				nofx_filename,
				fps,
				nofx[-error:]
			)


if __name__ == '__main__':
	if len(sys.argv) != 2:
		print('使い方:')
		print(
			'python sdvx2ksh.py '
			'https://sdvx.in/05/05004m.htm'
		)
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

		### NEW:
		# 解析開始前に使用するURLを表示する。
		print('bg URL   : ' + score.url['bg'])
		print('data URL : ' + score.url['data'])
		print('bar URL  : ' + score.url['bar'])

		body = parseScore(score)

		filename = score.id + score._d + '.ksh'

		print('KSHファイルを書き込んでいます...')

		with codecs.open(
			filename,
			'w',
			'utf-8'
		) as f:
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
