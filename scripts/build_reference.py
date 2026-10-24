#!/usr/bin/env python3
"""建立人类参考语料与句式模板校准表（v3，arXiv 2407.00211 口径）。

两个量分工，不要混用：
  浓度（concentration）= 待测文本内部的模板复读率。每个窗口/文件自算 top20% 模板
      （与 v2 同口径，实测动态范围够用），按句数分档与人类同规模分位比较。
  溯源率 CDR = 待测文本的不同模板中，落在**人类参考语料全局高频集**里的比例。
      论文实测 AI 76% / 人类 35%；本表用留一法给出人类自己的区间。

v3 相对 v2 的修正：
  1. 校准语料从 2 本 4800 句扩到 3 本 36146 句（含古白话网文、中译严肃文学、中译毛姆），
     每档随机窗口重算，复读句占比一并入库。
  2. 新增 ref_templates.json（全语料不同模板 101984 条取高频 20%），CDR 从此有可比基线，
     不再是「基线 25 句、只当参考」的装饰指标。
  3. 留一法：book X 只与其余书建的模板集比较，避免自包含把人类基线抬成 1.0。
  4. 语料本体放仓库外（版权），仓库只放聚合统计与模板集。

用法：
  python3 scripts/build_reference.py --corpus /root/prose-deai-corpus
"""
import argparse
import collections
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tplcore as T  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.normpath(os.path.join(HERE, '..'))
SIZES = (20, 50, 100, 300, 1000, 2000)
WINDOWS = {20: 400, 50: 400, 100: 300, 300: 120, 1000: 40, 2000: 20}
K_TOP = 10


def extract_epub(path, out_txt):
    import html
    import zipfile
    z = zipfile.ZipFile(path)
    names = sorted(n for n in z.namelist() if n.lower().endswith(('.xhtml', '.html', '.htm')))
    tag = re.compile(r'<(script|style)[^>]*>.*?</\1>', re.S | re.I)
    parts = []
    for n in names:
        raw = z.read(n).decode('utf-8', 'ignore')
        raw = tag.sub(' ', raw)
        raw = re.sub(r'<(p|br|div|h[1-6])[^>]*>', '\n', raw, flags=re.I)
        parts.append(html.unescape(re.sub(r'<[^>]+>', '', raw)))
    txt = T.clean_text('\n'.join(parts))
    with open(out_txt, 'w', encoding='utf-8') as f:
        f.write(txt)
    return txt


def load_rows(cache_path, txt_path, n):
    """POS 序列缓存：jieba 一遍几十分钟，重算校准表时不该再跑一次。"""
    if os.path.exists(cache_path):
        rows = []
        with open(cache_path, encoding='utf-8') as f:
            for line in f:
                d = json.loads(line)
                rows.append((d['s'], d['g']))
        return rows
    rows = T.sent_rows(T.load_text(txt_path), n)
    with open(cache_path, 'w', encoding='utf-8') as f:
        for s, g in rows:
            f.write(json.dumps({'s': s, 'g': g}, ensure_ascii=False) + '\n')
    return rows


def doc_metrics(rows):
    """窗口/文件自算 top20% 模板下的结构特征（与检测器同一函数，口径不可能漂）。"""
    return T.doc_feats(rows, None, k=K_TOP)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus', required=True, help='语料目录（含 text/、pos/）')
    ap.add_argument('--epub', action='append', default=[], help='name=epub 路径，可多次')
    ap.add_argument('--n', type=int, default=5)
    ap.add_argument('--seed', type=int, default=20261025)
    ap.add_argument('--out', default=os.path.join(SKILL, 'corpus'))
    a = ap.parse_args()
    if not T.HAS_JIEBA:
        sys.exit('需要 jieba：pip install jieba')

    tdir = os.path.join(a.corpus, 'text')
    pdir = os.path.join(a.corpus, 'pos')
    os.makedirs(tdir, exist_ok=True)
    os.makedirs(pdir, exist_ok=True)
    for spec in a.epub:
        name, _, path = spec.partition('=')
        txt = extract_epub(path, os.path.join(tdir, f'{name}.txt'))
        print(f'[extract] {name} {len(txt)/10000:.1f} 万字', flush=True)

    books = {}
    for f in sorted(os.listdir(tdir)):
        if not f.endswith('.txt'):
            continue
        name = f[:-4]
        books[name] = load_rows(os.path.join(pdir, f'{name}.n{a.n}.jsonl'),
                                os.path.join(tdir, f), a.n)
        print(f'[pos] {name}: {len(books[name])} 句', flush=True)
    if len(books) < 2:
        sys.exit('至少需要两本书做留一法基线')

    # 全局模板集（溯源用）
    pooled = collections.Counter()
    for rows in books.values():
        for _, g in rows:
            pooled.update(g)
    ref_top, k = T.top_set(pooled, T.TOP_PCT)
    print(f'[ref] 不同模板 {len(pooled)}，高频集 {k}', flush=True)

    full, cdr_hold = {}, {}
    for name, rows in books.items():
        cnt = collections.Counter()
        for _, g in rows:
            cnt.update(g)
        fm = doc_metrics(rows)
        conc, rep = fm['conc'], fm['rep']
        full[name] = {'sentences': len(rows), 'templates': len(cnt),
                      'conc': round(conc, 4), 'rep': round(rep, 4)}
        other = collections.Counter()
        for j, rs in books.items():
            if j == name:
                continue
            for _, g in rs:
                other.update(g)
        o_top, _ = T.top_set(other, T.TOP_PCT)
        cdr_hold[name] = len(set(cnt) & o_top) / len(cnt)
        print(f"[book] {name} 句={len(rows)} 模板={len(cnt)} 浓度={full[name]['conc']} "
              f"复读句={full[name]['rep']} 留一法CDR={cdr_hold[name]:.4f}", flush=True)
    cdr_vals = list(cdr_hold.values())

    rng = random.Random(a.seed)
    # 留一法模板集：book X 的窗口只跟其余书建的模板集比 CDR
    hold_top = {}
    for name in books:
        c = collections.Counter()
        for j, rs in books.items():
            if j == name:
                continue
            for _, g in rs:
                c.update(g)
        hold_top[name], _ = T.top_set(c, T.TOP_PCT)

    bins = []
    for size in SIZES:
        acc = collections.defaultdict(list)
        for name, rows in books.items():
            if len(rows) < size:
                continue
            for _ in range(WINDOWS[size]):
                start = rng.randrange(0, len(rows) - size + 1)
                w = rows[start:start + size]
                f = T.doc_feats(w, ref_top, k=K_TOP)
                d = set(x for _, g in w for x in g)
                f['cdr'] = len(d & hold_top[name]) / len(d)      # 留一法
                f['cdrg'] = len(d & ref_top) / len(d)            # 全局（与检测器同口径）
                for key, val in f.items():
                    if key != 'n':
                        acc[key].append(val)
        if not acc.get('tci'):
            continue
        b = {'n': size, 'windows': len(acc['tci'])}
        for key in ('tci', 'cv', 'rep', 'conc', 'refc', 'cdr', 'cdrg'):
            b[key] = {q: round(T.pct(acc[key], v), 4) for q, v in
                      (('p10', .1), ('p50', .5), ('p90', .9))}
        b['cdr']['max'] = round(max(acc['cdr']), 4)
        b['cdrg']['max'] = round(max(acc['cdrg']), 4)
        bins.append(b)
        print(f"[bin] {size:>4}句 TCI10 {b['tci']['p10']}/{b['tci']['p50']}/{b['tci']['p90']} "
              f"CV {b['cv']['p10']}/{b['cv']['p50']}/{b['cv']['p90']} "
              f"复读句 {b['rep']['p50']}/{b['rep']['p90']} CDR {b['cdr']['p50']}/{b['cdr']['max']}",
              flush=True)

    calib = {
        'version': 3,
        'n': a.n,
        'unit': 'pos5：粗词性 5-gram，浅层句法代理，非成分树模板（见 SKILL.md §8.2）',
        'k_top': K_TOP,
        'ref': 'corpus/ref_templates.json',
        'note': '人类基线：每档随机窗口自算 top20% 模板，给出 tci(前10模板token占比)、'
                'cv(句长变异系数)、rep(复读句占比)、conc、refc，以及留一法 CDR 分位',
        'books': {k2: v for k2, v in full.items()},
        'bins': bins,
        'provenance': {
            'metric': 'CDR = 待测文本不同模板中落在人类参考高频集(20%)里的比例',
            'human_holdout_cdr': {k2: round(v, 4) for k2, v in cdr_hold.items()},
            'human_band': {'p50': round(T.pct(cdr_vals, .5), 4),
                           'max': round(max(cdr_vals), 4)},
            'size_matched': '判 CDR 请用 bins[].cdr（同句数留一法分位），book 级数字只说明作品间差异',
            'paper': '论文实测 AI 76% / 人类 35%（英文成分树模板），本表为可比的本地口径',
            'limit': '人类样本 3 部作品；band 是观测区间，不是统计下界',
        },
        'meta': {'top_pct': T.TOP_PCT, 'strong': T.STRONG, 'seed': a.seed},
    }

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, 'ref_templates.json'), 'w', encoding='utf-8') as f:
        json.dump({'n': a.n, 'top_pct': T.TOP_PCT, 'templates': sorted(ref_top)},
                  f, ensure_ascii=False)
    with open(os.path.join(a.out, 'calibration.json'), 'w', encoding='utf-8') as f:
        json.dump(calib, f, ensure_ascii=False, indent=1)
    print(f"[done] {a.out}/calibration.json + ref_templates.json "
          f"({os.path.getsize(os.path.join(a.out, 'ref_templates.json'))//1024} KB)")


if __name__ == '__main__':
    main()
