#!/usr/bin/env python3
"""句式模板检测 v3 —— arXiv 2407.00211 的本地口径（多指标 + 参考语料校准）。

判据（全部与人类同句数分位比较，见 corpus/calibration.json）
  TCI10  模板集中度：频次最高的 10 个 POS 5-gram 覆盖了多少 token 质量。
         这是论文「模板复读」的直接代理：AI 反复复用少数骨架，人类叙事会散开。
         本机实测 AI 0.058–0.074 / 人类 0.014–0.021（约 300 句档），相差 3–4 倍。
  CV     句长变异系数：AI 句长分布窄（实测 0.20–0.29，人类 0.43–0.77）。
  rep    复读句占比：句级浓度 ≥0.5 的句子面积。用来定位，不单独定级。
  CDR    溯源率：本章不同模板中落在人类参考高频集（20%，20396 条）的比例，
         与同句数留一法人类分位比。论文 AI 76% / 人类 35%，本地 band 见 calibration。
  conc / refc  参考浓度：保留给 §7.3 跨章漂移与旧文档对照，不参与定级。

判级：按句数分档——≥100 句 强信号或 ≥2 信号→【句式模板化】/1 信号→【偏高】；
40–99 句只 T+R 同超 P90→【偏高】；<40 句→【样本短】只给句级榜。
v2 只用 doc-relative 浓度均值，实测被句长与文档长度带偏（300 句人类 P50 0.33，
60 句 AI 稿 0.22 反被判「正常」），故降为辅助指标。

用法:
  check_syntax_tpl.py <文件...> [--baseline 目录] [--calibration 路径] [--ref 路径]
                      [--n 5] [--fail-on blocking] [--json] [--quiet]

退出码：默认 0（advisory）；--fail-on=blocking 命中【句式模板化】时 1。
"""
import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tplcore as T  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CALIB = os.path.normpath(os.path.join(HERE, '..', 'corpus', 'calibration.json'))
DEFAULT_REF = os.path.normpath(os.path.join(HERE, '..', 'corpus', 'ref_templates.json'))
K_TOP = 10
KEYS = ('tci', 'cv', 'rep', 'conc', 'refc', 'cdr', 'cdrg')
SIGNAL_NAME = {'T': '模板集中度 TCI10 超人类 P90', 'R': '复读句面积超人类 P90',
               'C': '句长过匀（CV 低于人类 P10 的 75%）'}


def advice(tpls, sigs):
    out = []
    if 'T' in sigs:
        out.append('骨架在复用：相邻同骨架句换结构（主谓宾→状语前置/被动/独立成分）')
    if 'C' in sigs:
        out.append('句长过匀：插 2–3 个明显更长的复句，再断出 1–2 个短句')
    if 'R' in sigs:
        out.append('复读句扎堆：只改浓度 ≥0.5 的句子，别整段重写')
    s = set(tpls)
    if any(t[0] in 'AD' for t in s):
        out.append('句首修饰先落地：删修饰，让动词先出现')
    if any(t.count('U') >= 2 for t in s):
        out.append('助词链过密：拆句或删「的/地/得」')
    if any(t.count('N') >= 3 for t in s):
        out.append('名词块堆叠：改成「施动者+动词+对象」')
    if any(t[0] == 'R' for t in s):
        out.append('句首代词开场：删代词，直接上施动者')
    return out[:4]


def load_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def calib_at(bins, n):
    if not bins:
        return None
    bs = sorted(bins, key=lambda b: b['n'])
    if n <= bs[0]['n']:
        return bs[0]
    if n >= bs[-1]['n']:
        return bs[-1]
    for a, b in zip(bs, bs[1:]):
        if a['n'] <= n <= b['n']:
            t = (n - a['n']) / (b['n'] - a['n'])
            out = {'n': n}
            for k in KEYS:
                if k in a and k in b:
                    out[k] = {q: a[k][q] + t * (b[k][q] - a[k][q]) for q in a[k]}
            return out
    return bs[-1]


def judge(f, cal, nsent=0):
    """返回 (级别, 信号列表, 分位)。信号：T=模板集中 / R=复读句面积 / C=句长过匀。

    判级按样本长度分档——论文的模板复读是长文本累积现象，短样本的 TCI/rep
    受句长与文体（四字格、文言化短句）影响，20 句人类真品实测会同时超 P90。
      >=100 句：强信号或 >=2 信号 -> template；1 信号 -> high
      40-99 句：只 T 与 R 同超 P90（或强信号）-> high，不判 template
      <40 句：short，只给句级榜
    """
    sig = []
    if f['tci'] > cal['tci']['p90']:
        sig.append('T')
    if f['rep'] > cal['rep']['p90']:
        sig.append('R')
    if f['cv'] < 0.75 * cal['cv']['p10']:
        sig.append('C')   # 留 25% 余量：人类网文句长也会偏匀
    strong = f['tci'] > 2 * cal['tci']['p90']
    if nsent >= 100:
        level = 'template' if (strong or len(sig) >= 2) else ('high' if sig else 'normal')
    elif nsent >= 40:
        level = 'high' if (strong or ('T' in sig and 'R' in sig)) else 'normal'
    else:
        level = 'short'
    p10, p50, p90 = cal['tci']['p10'], cal['tci']['p50'], cal['tci']['p90']
    v = f['tci']
    if v <= p10:
        pct = max(1, round(v / max(1e-9, p10) * 10))
    elif v <= p50:
        pct = round(10 + (v - p10) / max(1e-9, p50 - p10) * 40)
    elif v <= p90:
        pct = round(50 + (v - p50) / max(1e-9, p90 - p50) * 40)
    else:
        pct = round(90 + min(1.0, (v - p90) / max(1e-9, p90)) * 9)
    return level, sig, pct


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('--baseline', default=None,
                    help='项目自基线：文件或目录。给了就用它建参考模板集（跨章口径统一）')
    ap.add_argument('--calibration', default=None, help='校准表；缺省 corpus/calibration.json')
    ap.add_argument('--ref', default=None, help='参考模板集；缺省 corpus/ref_templates.json')
    ap.add_argument('--n', type=int, default=5)
    ap.add_argument('--fail-on', default='none', choices=['none', 'blocking'],
                    help='blocking：判【句式模板化】时退出码 1')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()

    if not T.HAS_JIEBA:
        print('[syntax_tpl] 未安装 jieba，跳过（pip install jieba）')
        return 0

    calib = load_json(a.calibration or DEFAULT_CALIB) or {}
    bins = calib.get('bins')
    prov = calib.get('provenance') or {}

    ref_src, ref_top = 'none', set()
    if a.baseline and a.baseline != 'none':
        if os.path.isdir(a.baseline):
            base_txt, src = T.read_corpus_dir(a.baseline)
        elif os.path.exists(a.baseline):
            base_txt, src = T.load_text(a.baseline), a.baseline
        else:
            base_txt, src = None, 'missing'
        if base_txt:
            c = collections.Counter()
            for _, g in T.sent_rows(base_txt, a.n):
                c.update(g)
            ref_top, _ = T.top_set(c, T.TOP_PCT)
            ref_src = f'自基线:{src}'
    if not ref_top and a.baseline != 'none':
        doc = load_json(a.ref or DEFAULT_REF)
        if doc and doc.get('templates'):
            ref_top = set(doc['templates'])
            ref_src = a.ref or DEFAULT_REF
    global_ref = bool(ref_top) and not ref_src.startswith('自基线')

    report = {'n': a.n, 'k_top': K_TOP, 'ref': ref_src,
              'calibration': (a.calibration or DEFAULT_CALIB) if bins else None,
              'files': []}
    blocked = 0
    for path in a.files:
        rows = T.sent_rows(T.load_text(path), a.n)
        if not rows:
            continue
        sents = [s for s, _ in rows]
        cnt = collections.Counter()
        for _, g in rows:
            cnt.update(g)
        top, _ = T.top_set(cnt, T.TOP_PCT)          # 文件自算模板集（浓度口径）
        f = T.doc_feats(rows, ref_top if global_ref else None, k=K_TOP)
        distinct = set(cnt)
        cdr = round(len(distinct & ref_top) / len(distinct), 3) if global_ref and distinct else None
        cal = calib_at(bins, len(sents)) if bins else None
        level, sig, pct = judge(f, cal, len(sents)) if cal else (None, [], None)
        strong = [i for i, (_, g) in enumerate(rows) if T.conc(g, top) >= T.STRONG]
        all_tpl = [t for n_ in strong[:12] for t in rows[n_][1] if t in top]

        entry = {'file': path, 'sentences': len(sents), 'templates': len(distinct),
                 'tci': round(f['tci'], 4), 'cv': round(f['cv'], 3),
                 'mean_len': round(f['mean_len'], 1), 'rep_share': round(f['rep'], 3),
                 'conc': round(f['conc'], 3),
                 'refc': None if 'refc' not in f else round(f['refc'], 3),
                 'cdr': cdr,
                 'ref': None if not cal else {
                     'n': round(cal['n']),
                     'tci': {q: round(cal['tci'][q], 4) for q in ('p10', 'p50', 'p90')},
                     'cv': {q: round(cal['cv'][q], 3) for q in ('p10', 'p50', 'p90')},
                     'rep_p90': round(cal['rep']['p90'], 3),
                     'cdr_p90': None if 'cdrg' not in cal else round(cal['cdrg'].get('p90', 0), 3),
                     'cdr_max': None if 'cdrg' not in cal else round(cal['cdrg'].get('max', 0), 3)},
                 'level': level, 'signals': sig, 'percentile': pct,
                 'strong': len(strong), 'notes': [
                     {'idx': i + 1, 'conc': round(T.conc(rows[i][1], top), 2),
                      'sent': sents[i][:40],
                      'tpl': [t for t in rows[i][1] if t in top][:3]}
                     for i in strong[:12]]}
        report['files'].append(entry)
        hit = a.fail_on == 'blocking' and level == 'template'
        blocked += 1 if hit else 0

        if not a.quiet:
            flag = {'template': '【句式模板化】', 'high': '【偏高】', 'normal': '【正常】',
                    'short': '【样本短，看句级榜单】'}.get(level or '', '')
            print(f'\n[句式模板] {path} {flag}')
            print(f"  句={len(sents)} 平均句长={entry['mean_len']} 模板={len(distinct)}"
                  + (f" CDR={cdr}" if cdr is not None else ''))
            if entry['ref']:
                r = entry['ref']
                print(f"  TCI10={entry['tci']} 人类同规模 P10/P50/P90="
                      f"{r['tci']['p10']}/{r['tci']['p50']}/{r['tci']['p90']} 分位~P{pct}")
                print(f"  句长CV={entry['cv']} 人类 P10/P50/P90="
                      f"{r['cv']['p10']}/{r['cv']['p50']}/{r['cv']['p90']}")
                print(f"  复读句(≥0.5)={len(strong)}/{len(sents)} 占比={entry['rep_share']} "
                      f"人类P90={r['rep_p90']}")
                if cdr is not None and r['cdr_max'] is not None:
                    tag = '【高于人类上界】' if cdr > r['cdr_max'] else ''
                    print(f"  溯源 CDR 人类同句数 P90/max={r['cdr_p90']}/{r['cdr_max']}{tag}（<300 句只作诊断）")
            else:
                print(f"  TCI10={entry['tci']} 句长CV={entry['cv']} 复读句={len(strong)}/{len(sents)}")
            if sig:
                print('  信号：' + '；'.join(SIGNAL_NAME[s] for s in sig))
            for s_ in advice(all_tpl, sig):
                print(f'  修法: {s_}')
            for n_ in entry['notes'][:5]:
                print(f"    句{n_['idx']:>3} 浓度{n_['conc']:.2f} {n_['sent']}")
                print(f"        高频模板: {', '.join(n_['tpl'])}")
            if hit:
                print('  判定：FAIL —— 交付前必须改骨架（§7.1）。')
            elif level == 'template':
                print('  提示：结构特征超人类同规模区间，按 §7.1 换骨架，别逐词换，别整段重写。')
            elif level == 'high':
                print('  提示：单项信号偏高，只改命中的那几条。')
            elif level == 'short':
                print('  提示：样本 <40 句，按论文口径不做文件级判定，只看句级榜与 CDR。')

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if blocked else 0


if __name__ == '__main__':
    sys.exit(main())
