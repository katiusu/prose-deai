#!/usr/bin/env python3
"""句式模板层公共内核（arXiv 2407.00211 的本地口径）。

模板单位：粗词性 5-gram（与 calibration.json 的 n 一致）。
本模块只放纯函数，供 check_syntax_tpl.py 与 build_reference.py 共用，
保证建表与检测用同一套切句、词性映射，不会出现口径漂移。
"""
import collections
import math
import os
import re

try:
    import jieba
    import jieba.posseg as pseg
    jieba.setLogLevel(60)
    HAS_JIEBA = True
except Exception:  # pragma: no cover
    HAS_JIEBA = False
    pseg = None

# 12 类粗词性
M = {'n': 'N', 'nr': 'N', 'ns': 'N', 'nt': 'N', 'nz': 'N', 'ng': 'N', 'vn': 'N', 'an': 'N',
     'v': 'V', 'vd': 'V', 'vg': 'V', 'a': 'A', 'ad': 'A', 'ag': 'A',
     'd': 'D', 'df': 'D', 'u': 'U', 'uj': 'U', 'ul': 'U', 'uv': 'U', 'uz': 'U', 'ud': 'U',
     'ug': 'U', 'ui': 'U', 'p': 'P', 'c': 'C', 'r': 'R', 'rr': 'R', 'rz': 'R', 'm': 'M',
     'q': 'Q', 't': 'T', 'f': 'F', 's': 'S', 'b': 'B', 'z': 'Z', 'i': 'I', 'l': 'I'}
DROP = set('w x') | set('，、；：。！？…—')
TOP_PCT = 0.2          # 参考模板集 = 语料内频次最高的 20% 不同模板
STRONG = 0.5           # 句级强提示阈值

# epub 导航/版权页噪声行
_NOISE = re.compile(
    r'^(未知|目录|导航|封面|扉页|Contents|Landmarks|Table of Contents|'
    r'版权信息|图书在版编目.*|ISBN.*)$', re.I)


def split_sents(text):
    return [s.strip() for s in re.split(r'[。！？\n]+', text) if s.strip()]


def clean_text(raw):
    """去掉 epub 抽出的导航行与空行。"""
    out = []
    for line in raw.split('\n'):
        s = line.strip()
        if not s or _NOISE.match(s):
            continue
        # 无标点的短行基本是目录条目
        if len(s) <= 6 and not re.search(r'[。！？，；：”"]', s):
            continue
        out.append(s)
    return '\n'.join(out)


def pos_seq(sent):
    return [M.get(f, 'X') for w, f in pseg.cut(sent)
            if w.strip() and f not in DROP and w not in '，、；：。！？']


def ngrams(seq, n):
    return [''.join(seq[i:i + n]) for i in range(len(seq) - n + 1)]


def sent_rows(text, n):
    """返回 [(句子, 5-gram 列表)]，丢弃过短无模板的句子。"""
    rows = []
    for s in split_sents(text):
        g = ngrams(pos_seq(s), n)
        if g:
            rows.append((s, g))
    return rows


def conc(g, top):
    """单句模板浓度 = 该句 n-gram 落在参考高频模板集里的比例。"""
    return sum(1 for x in g if x in top) / len(g) if g else 0.0


def load_text(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def read_corpus_dir(path):
    """读目录下全部 .md/.txt，返回拼接文本与来源标记。"""
    if not path or not os.path.isdir(path):
        return None, 'missing'
    parts = [load_text(os.path.join(path, f)) for f in sorted(os.listdir(path))
             if f.endswith(('.md', '.txt'))]
    if not parts:
        return None, 'empty'
    return '\n'.join(parts), path


def entropy(cnt):
    total = sum(cnt.values())
    if total <= 0 or len(cnt) < 2:
        return 0.0
    return -sum((v / total) * math.log(v / total, 2) for v in cnt.values()) / math.log(len(cnt), 2)


def pct(vals, q):
    if not vals:
        return 0.0
    xs = sorted(vals)
    k = (len(xs) - 1) * q
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def counter_from_rows(rows):
    c = collections.Counter()
    for _, g in rows:
        c.update(g)
    return c


def top_set(cnt, pct_=TOP_PCT):
    """参考高频模板集：按频次取前 pct_ 比例的不同模板。"""
    k = max(1, int(len(cnt) * pct_))
    return {t for t, _ in cnt.most_common(k)}, k


def doc_feats(rows, ref_top=None, k=10):
    """文档级结构特征。rows=[(句子, 5-gram列表)]。

    tci   模板集中度：出现频次最高的 k 个模板覆盖了多少 n-gram token 质量。
          AI 输出反复复用少数骨架，这个值显著高（本机实测 AI 0.058–0.074 vs 人类 0.014–0.021）。
    cv    句长变异系数：AI 句子长度分布窄（0.20–0.29 vs 人类 0.43–0.77）。
    rep   复读句占比：句级浓度 ≥0.5 的句子比例。
    conc  句级浓度均值（文件自算 top20%，与校准表同口径）。
    refc  对参考语料高频集的浓度（跨语料对照用）。
    """
    import statistics as _st
    L = [len(s) for s, _ in rows]
    cnt = collections.Counter()
    for _, g in rows:
        cnt.update(g)
    total = sum(cnt.values()) or 1
    top, _ = top_set(cnt, TOP_PCT)
    ratios = [conc(g, top) for _, g in rows]
    f = {
        'n': len(rows),
        'mean_len': sum(L) / len(L) if L else 0.0,
        'cv': (_st.pstdev(L) / _st.mean(L)) if len(L) > 1 and _st.mean(L) else 0.0,
        'tci': sum(v for _, v in cnt.most_common(k)) / total,
        'conc': sum(ratios) / len(ratios) if ratios else 0.0,
        'rep': sum(1 for x in ratios if x >= STRONG) / len(ratios) if ratios else 0.0,
    }
    if ref_top:
        rs = [sum(1 for x in g if x in ref_top) / len(g) for _, g in rows]
        f['refc'] = sum(rs) / len(rs) if rs else 0.0
    return f
