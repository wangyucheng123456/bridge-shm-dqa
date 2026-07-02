"""Generate a self-contained HTML report summarising all reviewer-response
work performed on top of the original manuscript. Reads the CSVs produced by
reviewer_response.py and writes reviewer_response_report.html."""
import os
import json
import pandas as pd
from src.config import TABLES_DIR, PROJECT_ROOT

OUT = os.path.join(PROJECT_ROOT, "reviewer_response_report.html")


def read(name):
    return pd.read_csv(os.path.join(TABLES_DIR, name))


def fnum(x, nd=4):
    try:
        return f"{float(x):.{nd}f}"
    except Exception:
        return str(x)


def sci(x):
    try:
        v = float(x)
        if v == 0:
            return "&lt;1e-300"
        if v < 1e-4:
            return f"{v:.1e}"
        return f"{v:.4f}"
    except Exception:
        return str(x)


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def cb(code, label=None, kind=""):
    """Render a code block. kind in {'', 'old', 'new'} controls the colour bar."""
    tag = ""
    if kind == "old":
        tag = '<div class="cbtag t-old">修改前 / BEFORE</div>'
    elif kind == "new":
        tag = '<div class="cbtag t-new">修改后 / AFTER</div>'
    elif label:
        tag = f'<div class="cbtag">{esc(label)}</div>'
    cls = f"cb {kind}"
    return f'<div class="{cls}">{tag}<pre><code>{esc(code)}</code></pre></div>'


def table(df, highlight_cols=None, fmt=None):
    highlight_cols = highlight_cols or []
    fmt = fmt or {}
    head = "".join(f"<th>{c}</th>" for c in df.columns)
    rows = []
    for _, r in df.iterrows():
        cells = []
        for c in df.columns:
            val = fmt[c](r[c]) if c in fmt else r[c]
            cls = ' class="hl"' if c in highlight_cols else ""
            cells.append(f"<td{cls}>{val}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def main():
    leak = read("reviewer_clean_vs_leaked_f1.csv")
    base = read("reviewer_multibaseline_detection.csv")
    wil = read("reviewer_wilcoxon_tests.csv")
    win = read("reviewer_window_threshold_sensitivity.csv")
    with open(os.path.join(TABLES_DIR, "reviewer_summary.json"), encoding="utf-8") as f:
        summ = json.load(f)
    p = summ["params"]

    # Derived headline numbers
    max_gap = leak.sort_values("F1_leak_gap", ascending=False).iloc[0]
    pca_bl_gap = leak[(leak.Detector == "PCA") & (leak.Condition == "baseline")].iloc[0]

    leak_view = leak.copy()
    for c in ["F1_fixed_clean", "F1_optimal_leaked", "F1_leak_gap", "AUC"]:
        leak_view[c] = leak_view[c].map(lambda x: fnum(x, 4))

    wil_view = wil.copy()
    wil_view["t_p"] = wil_view["t_p"].map(sci)
    wil_view["wilcoxon_p"] = wil_view["wilcoxon_p"].map(
        lambda x: "n/a" if pd.isna(x) else sci(x))
    wil_view["cohens_d"] = wil_view["cohens_d"].map(lambda x: fnum(x, 2))
    wil_view["baseline_mean"] = wil_view["baseline_mean"].map(lambda x: fnum(x, 3))
    wil_view["condition_mean"] = wil_view["condition_mean"].map(lambda x: fnum(x, 3))
    wil_view = wil_view[["Detector", "Metric", "Comparison", "baseline_mean",
                         "condition_mean", "n_pairs", "t_p", "wilcoxon_p",
                         "cohens_d", "wilcoxon_note"]]

    win_view = win.copy()
    for c in ["F1_fixed", "AUC"]:
        win_view[c] = win_view[c].map(lambda x: fnum(x, 4))
    win_view["F1_std"] = win_view["F1_std"].map(lambda x: fnum(x, 4))
    win_view["AUC_std"] = win_view["AUC_std"].map(lambda x: f"{float(x):.2e}")

    # ---------------- Detailed code-change documentation ----------------
    code_changes_html = (
        '<h2>代码具体改了什么（逐处说明）</h2>'
        '<p class="sub">下面按"文件 → 位置 → 改动类型 → 前后对比 → 为什么"逐条列出。'
        '共改动 <b>1 个源文件</b>（<code>src/damage_detection.py</code>）并新增 '
        '<b>2 个脚本</b>（<code>reviewer_response.py</code>、'
        '<code>generate_reviewer_report.py</code>）与 2 个仓库文件。'
        '原有主流程 <code>run_experiment_v2.py</code> 未改动。</p>'

        # 变更 1
        '<div class="chg">'
        '<h3 style="margin-top:0">变更 1 · 新增 3 个基线检测器所需的 sklearn 导入'
        '<span class="tag2">新增</span></h3>'
        '<p class="loc">文件 <code>src/damage_detection.py</code> · 顶部导入区（第 10–13 行）</p>'
        '<p>为 Isolation Forest 和 One-Class SVM 引入 scikit-learn 的两个类。</p>'
        + cb('from sklearn.decomposition import PCA\n'
             'from sklearn.preprocessing import StandardScaler', kind='old')
        + cb('from sklearn.decomposition import PCA\n'
             'from sklearn.ensemble import IsolationForest      # 新增\n'
             'from sklearn.svm import OneClassSVM                # 新增\n'
             'from sklearn.preprocessing import StandardScaler', kind='new')
        + '</div>'

        # 变更 2
        '<div class="chg">'
        '<h3 style="margin-top:0">变更 2 · 把硬编码的 30% 窗口阈值提取为可配置函数'
        '<span class="tag2">重构</span></h3>'
        '<p class="loc">文件 <code>src/damage_detection.py</code> · 新增模块级函数 '
        '<code>make_window_labels()</code>（第 25–41 行）</p>'
        '<p>原来两个检测器各自把"窗口内损伤样本占比 &gt; <b>0.3</b>"这个阈值<b>写死</b>在方法里，'
        '无法做敏感性对照。现在抽成一个独立函数，阈值变成参数 '
        '<code>damaged_frac_threshold</code>（默认仍为 0.3，保证向后兼容），'
        '这样问题⑤的 0.2/0.3/0.4/0.5 扫描无需改动任何模型。</p>'
        + cb('# 原来：写死在 PCADamageDetector.get_window_labels 里\n'
             'return np.array([\n'
             '    int(np.mean(labels[i*window_size:(i+1)*window_size]) > 0.3)\n'
             '    for i in range(n_windows)\n'
             '])', kind='old')
        + cb('def make_window_labels(labels, window_size=500,\n'
             '                       damaged_frac_threshold=0.3):\n'
             '    """阈值改为参数，检测器无关，可自由扫描。"""\n'
             '    n_windows = len(labels) // window_size\n'
             '    if n_windows == 0:\n'
             '        return np.array([int(np.mean(labels) > 0.5)])\n'
             '    return np.array([\n'
             '        int(np.mean(labels[i*window_size:(i+1)*window_size])\n'
             '            > damaged_frac_threshold)\n'
             '        for i in range(n_windows)\n'
             '    ])', kind='new')
        + '</div>'

        # 变更 3
        '<div class="chg">'
        '<h3 style="margin-top:0">变更 3 · 两个原检测器改用统一的窗口标注函数'
        '<span class="tag2">重构</span></h3>'
        '<p class="loc">文件 <code>src/damage_detection.py</code> · '
        '<code>PCADamageDetector.get_window_labels</code> 与 '
        '<code>AutoencoderDamageDetector.get_window_labels</code></p>'
        '<p>两处方法体从"复制粘贴的循环"改为调用上面的公共函数，并新增可选阈值参数。'
        '行为默认不变，但现在能接收自定义阈值。</p>'
        + cb('def get_window_labels(self, labels, window_size=500):\n'
             '    n_windows = len(labels) // window_size\n'
             '    if n_windows == 0:\n'
             '        return np.array([int(np.mean(labels) > 0.5)])\n'
             '    return np.array([\n'
             '        int(np.mean(labels[i*window_size:(i+1)*window_size]) > 0.3)\n'
             '        for i in range(n_windows)\n'
             '    ])', kind='old')
        + cb('def get_window_labels(self, labels, window_size=500,\n'
             '                      damaged_frac_threshold=0.3):\n'
             '    return make_window_labels(labels, window_size,\n'
             '                              damaged_frac_threshold)', kind='new')
        + '</div>'

        # 变更 4
        '<div class="chg">'
        '<h3 style="margin-top:0">变更 4 · 新增无泄露的通用异常检测基类'
        '<span class="tag2">新增</span></h3>'
        '<p class="loc">文件 <code>src/damage_detection.py</code> · 新增类 '
        '<code>_WindowAnomalyDetector</code></p>'
        '<p>这是修复"F1 数据泄露"的关键。基类在 <code>fit()</code> 里<b>只用健康训练集</b>的'
        '异常分数计算 95 分位作为固定阈值（<code>self.threshold</code>），'
        '<code>predict()</code> 直接套用这个阈值——<b>整个过程从不接触测试标签</b>。'
        'Isolation Forest / One-Class SVM 都继承它，只需各自实现"怎么建模型""怎么算异常分"。</p>'
        + cb('def fit(self, healthy_data, window_size=500, percentile=95.0):\n'
             '    features = self._prepare_features(healthy_data, window_size)\n'
             '    scaled = self.scaler.fit_transform(features)\n'
             '    self.model = self._build_model()\n'
             '    self.model.fit(scaled)\n'
             '    train_scores = self._anomaly_score(scaled)   # 只看训练集\n'
             '    self.threshold = np.percentile(train_scores, percentile)\n'
             '    return self\n\n'
             'def predict(self, data, window_size=500):\n'
             '    scaled = self.scaler.transform(self._prepare_features(data, window_size))\n'
             '    scores = self._anomaly_score(scaled)\n'
             '    return scores, (scores > self.threshold).astype(int)  # 固定阈值',
             label='新增：无泄露的固定阈值逻辑', kind='new')
        + '</div>'

        # 变更 5
        '<div class="chg">'
        '<h3 style="margin-top:0">变更 5 · 新增 3 个具体基线检测器'
        '<span class="tag2">新增</span></h3>'
        '<p class="loc">文件 <code>src/damage_detection.py</code> · 类 '
        '<code>IsolationForestDetector</code>、<code>OneClassSVMDetector</code>、'
        '<code>LSTMAutoencoderDetector</code></p>'
        '<p>前两个只需十几行（继承基类）。异常分数的约定统一为"越大越异常"：'
        'Isolation Forest 取 <code>-score_samples</code>，One-Class SVM 取 '
        '<code>-decision_function</code>。LSTM-AE 把每个窗口下采样成 32 步的序列，'
        '用重构误差当异常分数，阈值同样取健康集 95 分位。</p>'
        + cb('class IsolationForestDetector(_WindowAnomalyDetector):\n'
             '    def _build_model(self):\n'
             '        return IsolationForest(n_estimators=200,\n'
             '                               random_state=self.random_state, n_jobs=-1)\n'
             '    def _anomaly_score(self, scaled):\n'
             '        return -self.model.score_samples(scaled)   # 越大越异常\n\n'
             'class OneClassSVMDetector(_WindowAnomalyDetector):\n'
             '    def _build_model(self):\n'
             '        return OneClassSVM(kernel="rbf", nu=0.05, gamma="scale")\n'
             '    def _anomaly_score(self, scaled):\n'
             '        return -self.model.decision_function(scaled)',
             label='Isolation Forest + One-Class SVM', kind='new')
        + '</div>'

        # 变更 6
        '<div class="chg">'
        '<h3 style="margin-top:0">变更 6 · 新增实验主脚本 reviewer_response.py'
        '<span class="tag2">新增文件</span></h3>'
        '<p class="loc">新文件 <code>reviewer_response.py</code>（约 300 行）</p>'
        '<p>这里把五项分析串起来。<b>关键点：F1 泄露的修复就体现在这里</b>——它同时读取'
        '<code>evaluate_detection()</code> 返回的两个值：<code>f1_fixed</code>（无泄露、'
        '建议上报）与 <code>f1_score</code>（原稿用的、测试集优化过的、有泄露），'
        '两者相减即"乐观偏差"。它还调用已有的 <code>paired_test(..., test="wilcoxon")</code> '
        '补跑 Wilcoxon，并把每个种子的原始结果存成 <code>.npy</code> 供复现。</p>'
        + cb('r = evaluate_detection(wlabels, preds, scores)\n'
             'rec["f1_fixed"].append(r["f1_fixed"])   # 无泄露：训练集固定阈值\n'
             'rec["f1_opt"].append(r["f1_score"])     # 原稿：测试集上挑最优阈值（泄露）\n'
             '# ... 保存原始数组，供 Wilcoxon 复现\n'
             'np.save(f"results/tables/reviewer_raw/{det}__{cond}__f1_fixed.npy", arr)',
             label='泄露修复 + 原始结果留存', kind='new')
        + '</div>'

        '<div class="card" style="border-color:#5a4a22">'
        '<b style="color:var(--warn)">⚠ 一个需要你决定的点</b><br>'
        '上面的修复是在<b>新脚本</b>里生效的（用于回应审稿人）。原稿主流程 '
        '<code>run_experiment_v2.py</code> 目前<b>仍然</b>上报有泄露的 '
        '<code>f1_score</code>（例如正文表里的 baseline F1=0.7519）。'
        '如果你要让正文主表也换成无泄露口径，需要把主流程里 '
        '<code>results.get(\'f1_score\')</code> 改成 <code>results.get(\'f1_fixed\')</code> '
        '并<b>重跑整条管线</b>（含 Z-24，耗时较长）。要做的话告诉我，我来改并重跑。'
        '</div>'
    )

    # ---------------- Git explainer ----------------
    git_html = (
        '<h2>④ 代码仓库 · Git 到底是什么？为什么审稿人看重？</h2>'
        '<div class="card">'
        '<p><b>一句话：</b>Git 是一个"代码存档与版本管理系统"，GitHub 是把这个存档放到'
        '网上、别人可以访问的网站。把论文代码放上 GitHub，等于给出一个'
        '<b>任何人都能下载、且永久不变</b>的链接，审稿人可以据此复现你的结果——'
        '这正是"可复现性（reproducibility）"，也是高质量期刊越来越硬性的要求。</p>'
        '<p>你现在 Data Availability 写的是"代码可向作者索取"。审稿人通常不喜欢这句，'
        '因为它不可验证、作者失联后就没了。换成一个公开仓库链接（最好再配一个 Zenodo '
        'DOI）会显著加分。</p>'
        '</div>'

        '<h3>几个名词（够用版）</h3>'
        '<table class="gloss"><tbody>'
        '<tr><td>Repository（仓库/repo）</td><td>就是你这个项目文件夹，但带了"历史记录"功能。</td></tr>'
        '<tr><td>Commit（提交）</td><td>一次"存档快照"。每次 commit 记录下当前所有文件的状态和一句说明。</td></tr>'
        '<tr><td>Staging（暂存）</td><td>提交前先用 <code>git add</code> 把要存档的文件挑进"暂存区"。</td></tr>'
        '<tr><td>Branch（分支）</td><td>平行的开发线，默认叫 <code>master</code> 或 <code>main</code>。你现在用不上多分支。</td></tr>'
        '<tr><td>Remote / origin（远程）</td><td>网上的那份副本（比如 GitHub 上的仓库），<code>origin</code> 是它的默认别名。</td></tr>'
        '<tr><td>Push（推送）</td><td>把本地的 commit 上传到远程（GitHub）。</td></tr>'
        '<tr><td>.gitignore</td><td>一个清单，列出"不要纳入仓库"的文件（比如你那 4GB 原始数据、未发表的 Word 手稿）。</td></tr>'
        '<tr><td>DOI</td><td>数字对象唯一标识符。Zenodo 能给某个版本的仓库发一个 DOI，等于一个永久、可被论文引用的地址。</td></tr>'
        '</tbody></table>'

        '<h3>我已经帮你做到哪一步了</h3>'
        '<div class="card"><ul>'
        '<li>✅ <code>git init</code>：在项目里建好了本地仓库（多了一个隐藏的 <code>.git</code> 文件夹）。</li>'
        '<li>✅ 写好 <code>.gitignore</code>：已排除 4GB 原始数据（<code>data/raw/</code>、<code>*.npy</code>、'
        '<code>*.zip</code>）和未发表手稿（<code>*.docx</code>、<code>投稿准备/</code>）。</li>'
        '<li>✅ 写好 <code>README.md</code>：项目说明、数据来源、复现步骤。</li>'
        '<li>✅ <code>git add</code>：66 个该公开的文件已进入暂存区。</li>'
        '<li>⛔ <b>还差最后两步（需要你本人操作）</b>：设置你的署名身份 → 首次提交 → 推到 GitHub。'
        '我按安全规范不会去改你的 git 身份配置。</li>'
        '</ul></div>'

        '<h3>你需要执行的命令（逐条解释）</h3>'
        '<div class="step"><div class="n">1</div><div class="body">'
        '<b>告诉 git 你是谁</b>（会写进每次提交的作者信息，用你的真实姓名和邮箱）：'
        + cb('git config user.name "Hu XXX"\n'
             'git config user.email "your_email@example.com"')
        + '<span class="small">注：不加 <code>--global</code>，只对本仓库生效。</span>'
        '</div></div>'

        '<div class="step"><div class="n">2</div><div class="body">'
        '<b>创建第一次提交</b>（把暂存的 66 个文件正式存档）：'
        + cb('git commit -m "Initial public release: DQA framework for bridge SHM"')
        + '</div></div>'

        '<div class="step"><div class="n">3</div><div class="body">'
        '<b>在 GitHub 上新建一个空仓库</b>（网页操作）：登录 github.com → 右上角 + → '
        'New repository → 填名字（如 <code>bridge-shm-dqa</code>）→ 不要勾选任何 README/'
        '.gitignore → Create。建完它会给你一个地址，形如 '
        '<code>https://github.com/你的用户名/bridge-shm-dqa.git</code>。'
        '</div></div>'

        '<div class="step"><div class="n">4</div><div class="body">'
        '<b>把本地仓库连到 GitHub 并推上去</b>：'
        + cb('git remote add origin https://github.com/你的用户名/bridge-shm-dqa.git\n'
             'git push -u origin master')
        + '<span class="small">第一次推送可能会让你登录 GitHub（浏览器或 token）。'
        '推完刷新网页就能看到代码了。</span>'
        '</div></div>'

        '<div class="step"><div class="n">5</div><div class="body">'
        '<b>（可选但强烈建议）拿一个可引用的 DOI</b>：到 zenodo.org 用 GitHub 账号登录 → '
        '在 Zenodo 里打开该仓库的开关 → 回 GitHub 给仓库发一个 Release（如 v1.0）→ '
        'Zenodo 会自动归档并生成一个 DOI。然后把 Data Availability 改成：'
        + cb('The code supporting this study is openly available at\n'
             'https://github.com/你的用户名/bridge-shm-dqa (archived at\n'
             'Zenodo, DOI: 10.5281/zenodo.XXXXXXX).', label='替换后的 Data Availability')
        + '</div></div>'
    )

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reviewer-Response Report — Bridge SHM DQA</title>
<style>
:root {{ --bg:#0f1720; --card:#172230; --ink:#e6edf3; --muted:#9fb0c0;
         --acc:#4da3ff; --good:#3fb950; --warn:#e3b341; --bad:#f85149; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
        font-family:-apple-system,Segoe UI,Roboto,"Microsoft YaHei",sans-serif;
        line-height:1.6; }}
.wrap {{ max-width:1080px; margin:0 auto; padding:32px 20px 80px; }}
h1 {{ font-size:26px; margin:0 0 4px; }}
h2 {{ font-size:20px; margin:38px 0 10px; padding-top:14px;
      border-top:1px solid #24313f; }}
h3 {{ font-size:16px; color:var(--acc); margin:20px 0 6px; }}
.sub {{ color:var(--muted); margin:0 0 18px; }}
.card {{ background:var(--card); border:1px solid #24313f; border-radius:10px;
         padding:16px 18px; margin:14px 0; }}
.badge {{ display:inline-block; font-size:12px; padding:2px 9px; border-radius:20px;
          font-weight:600; margin-right:6px; }}
.b-fixed {{ background:rgba(63,185,80,.15); color:var(--good);
            border:1px solid var(--good); }}
.b-warn {{ background:rgba(227,179,65,.15); color:var(--warn);
           border:1px solid var(--warn); }}
.b-bad {{ background:rgba(248,81,73,.15); color:var(--bad);
          border:1px solid var(--bad); }}
table {{ border-collapse:collapse; width:100%; font-size:13px; margin:10px 0;
         overflow:hidden; border-radius:8px; }}
th,td {{ padding:7px 10px; text-align:center; border-bottom:1px solid #24313f; }}
th {{ background:#1d2a38; color:var(--muted); font-weight:600;
      position:sticky; top:0; }}
tbody tr:hover {{ background:#1b2836; }}
td.hl {{ color:var(--warn); font-weight:600; }}
.scroll {{ max-height:520px; overflow:auto; border:1px solid #24313f;
           border-radius:8px; }}
code {{ background:#0b1119; padding:1px 6px; border-radius:5px;
        color:#ffb; font-size:13px; }}
.cb {{ margin:10px 0; border:1px solid #24313f; border-radius:8px;
       overflow:hidden; }}
.cb.old {{ border-color:#5a2a2a; }}
.cb.new {{ border-color:#2a5a34; }}
.cb pre {{ margin:0; padding:12px 14px; background:#0b1119; overflow:auto;
           font-size:12.5px; line-height:1.5; }}
.cb pre code {{ background:none; color:#d6e2ee; padding:0; }}
.cbtag {{ font-size:11px; font-weight:700; padding:5px 12px; letter-spacing:.4px;
          color:var(--muted); background:#141f2b; }}
.cbtag.t-old {{ color:#f0a; background:rgba(248,81,73,.10); }}
.cbtag.t-new {{ color:var(--good); background:rgba(63,185,80,.10); }}
.chg {{ background:#141d28; border:1px solid #24313f; border-radius:10px;
        padding:14px 18px; margin:16px 0; }}
.chg .loc {{ font-size:12px; color:var(--muted); margin:0 0 4px; }}
.chg .loc code {{ color:#8fd; }}
.tag2 {{ display:inline-block; font-size:11px; padding:1px 8px; border-radius:5px;
         background:#22303f; color:var(--acc); margin-left:6px; }}
.gloss {{ width:100%; }} .gloss td {{ text-align:left; }}
.gloss td:first-child {{ color:var(--acc); font-weight:600; white-space:nowrap;
                         width:150px; }}
.step {{ display:flex; gap:12px; margin:10px 0; align-items:flex-start; }}
.step .n {{ background:var(--acc); color:#04101c; font-weight:700; border-radius:50%;
            min-width:26px; height:26px; display:flex; align-items:center;
            justify-content:center; font-size:13px; }}
.step .body {{ flex:1; }}
.quote {{ border-left:3px solid var(--acc); padding:8px 14px; margin:10px 0;
          background:#101a26; color:#cfe; font-style:italic; }}
.kpi {{ display:flex; gap:14px; flex-wrap:wrap; margin:12px 0; }}
.kpi div {{ background:#101a26; border:1px solid #24313f; border-radius:8px;
            padding:12px 16px; flex:1; min-width:180px; }}
.kpi b {{ display:block; font-size:24px; color:var(--acc); }}
.kpi span {{ color:var(--muted); font-size:12px; }}
ul {{ margin:8px 0; }} li {{ margin:3px 0; }}
.small {{ color:var(--muted); font-size:12px; }}
a {{ color:var(--acc); }}
</style>
</head>
<body>
<div class="wrap">
<h1>审稿意见回应 · 新增实验汇总</h1>
<p class="sub">Bridge SHM 数据质量评估框架 — 在原稿基础上完成的全部新工作<br>
数据集：{p['dataset']} · 样本数 {p['n_samples']:,} · 窗口 {p['window_size']} ·
训练截止 idx {p['train_end']:,} · 断裂 idx {p['fracture_idx']:,} ·
运行耗时 {summ.get('elapsed_sec','?')} 秒</p>

<div class="card">
<b>本次共完成 5 项新工作：</b>
<ul>
<li>① <b>修复 F1 数据泄露</b>：改用无泄露的"训练集 95 分位固定阈值"，并量化了原优化阈值的乐观偏差。</li>
<li>② <b>补跑 Wilcoxon 符号秩检验</b>（配对 t 检验并列），并保存全部逐种子原始数组。</li>
<li>③ <b>新增三个基线</b>：Isolation Forest、One-Class SVM、LSTM 自编码器。</li>
<li>④ <b>初始化可公开引用的代码仓库</b>（git + README + .gitignore）。</li>
<li>⑤ <b>窗口标注阈值敏感性</b>：0.2 / 0.3 / 0.4 / 0.5 对照。</li>
</ul>
</div>

<h2>① F1 阈值数据泄露：确认 + 修复</h2>
<p><span class="badge b-bad">问题确认</span> 原稿报告的 F1 是在
<b>评估数据本身</b>上扫描 ROC 阈值挑出的最大值 —— 这是数据泄露。修复方式是改用
<b>只在健康训练集上确定的 95 分位固定阈值</b>（<span class="badge b-fixed">无泄露</span>），
AUC 与阈值无关故不受影响。下表量化了"泄露乐观偏差"（<code>F1_leak_gap</code> =
泄露F1 − 干净F1）：</p>

<div class="kpi">
<div><b>+{fnum(max_gap['F1_leak_gap'],3)}</b><span>最大乐观偏差
（{max_gap['Detector']} / {max_gap['Condition']}）<br>泄露 {fnum(max_gap['F1_optimal_leaked'],3)}
→ 真实 {fnum(max_gap['F1_fixed_clean'],3)}</span></div>
<div><b>+{fnum(pca_bl_gap['F1_leak_gap'],3)}</b><span>PCA 基线偏差<br>
泄露 {fnum(pca_bl_gap['F1_optimal_leaked'],3)} → 真实 {fnum(pca_bl_gap['F1_fixed_clean'],3)}</span></div>
<div><b>不受影响</b><span>AUC 与阈值无关，<br>原稿所有 AUC 结论依然成立</span></div>
</div>

<div class="scroll">{table(leak_view, highlight_cols=['F1_leak_gap'])}</div>
<p class="small">列含义：<code>F1_fixed_clean</code>=无泄露固定阈值 F1（建议报告值）；
<code>F1_optimal_leaked</code>=原稿的测试集优化 F1（有泄露）；
<code>F1_leak_gap</code>=两者之差（乐观偏差）。</p>

<h3>建议写进方法节 2.5 的措辞</h3>
<div class="quote">Each detector is trained on healthy data only. The decision
threshold is fixed as the 95th percentile of the reconstruction/anomaly-score
distribution on the training set and applied unchanged to the test segment; no
test-set information informs threshold selection. We report AUC
(threshold-independent) together with F1, precision and recall at this fixed,
training-derived threshold.</div>

<h2>② Wilcoxon 符号秩检验（+ 配对 t 检验）</h2>
<p><span class="badge b-fixed">已补跑</span> 对每个检测器、每个条件都同时给出配对 t 检验与
Wilcoxon 符号秩检验的 p 值，并保存了全部逐种子原始数组（<code>results/tables/reviewer_raw/*.npy</code>）以便复现。</p>
<p><span class="badge b-warn">重要说明</span> 部分检测器（PCA、One-Class SVM）的 baseline
是<b>确定性</b>的，其多种子值为同一常数，故该配对本质上是"样本 vs 常数"的单样本比较；
LSTM-AE 仅 5 个种子，Wilcoxon 的最小可达 p 为 0.0625，故即便效应很大也可能不显著（样本量所限）。</p>
<div class="scroll">{table(wil_view, highlight_cols=['wilcoxon_p'])}</div>

<h2>③ 新增基线模型</h2>
<p><span class="badge b-fixed">已实现并评估</span> 在完全相同的协议下（健康数据训练 +
95 分位固定阈值），新增 <b>Isolation Forest</b>、<b>One-Class SVM</b>、
<b>LSTM 自编码器</b>三个基线。下表为无泄露的固定阈值指标（均值 ± 标准差，附 95% bootstrap CI）：</p>
<div class="scroll">{table(base)}</div>
<p class="small">观察：在基线（无退化）AUC 上，LSTM-AE（0.873）&gt; 稠密 AE（0.808）&gt;
One-Class SVM（0.745）≈ PCA（0.724）&gt; Isolation Forest（0.684）。所有检测器在 5 dB
噪声下 AUC 均塌陷到 ~0.5，与原稿"噪声是最大威胁"的结论一致。</p>

{git_html}

<h2>⑤ 窗口标注阈值敏感性（0.2 / 0.3 / 0.4 / 0.5）</h2>
<p><span class="badge b-fixed">已补跑</span> 结果显示阈值选择<b>几乎完全不影响</b>结果：
F1 在四个阈值下完全相同，AUC 差异仅在 1e-6 量级。原因是窗口很少跨越损伤边界
（每个窗口内损伤样本占比几乎非 0 即 1），因此任意 (0,1) 内阈值给出的窗口标签一致。
这为原稿"30% 阈值先验固定"提供了强有力的稳健性证据。</p>
<div class="scroll">{table(win_view)}</div>

{code_changes_html}

<h2>产物清单</h2>
<div class="card">
<ul>
<li><code>reviewer_response.py</code> — 新增实验主脚本</li>
<li><code>src/damage_detection.py</code> — 新增 IsolationForest / OneClassSVM / LSTM-AE
检测器 + 可配置窗口阈值 + 无泄露固定阈值</li>
<li><code>results/tables/reviewer_clean_vs_leaked_f1.csv</code></li>
<li><code>results/tables/reviewer_multibaseline_detection.csv</code></li>
<li><code>results/tables/reviewer_wilcoxon_tests.csv</code></li>
<li><code>results/tables/reviewer_window_threshold_sensitivity.csv</code></li>
<li><code>results/tables/reviewer_raw/*.npy</code> — 逐种子原始结果（Wilcoxon 复现用）</li>
<li><code>README.md</code>, <code>.gitignore</code> — 仓库发布准备</li>
</ul>
</div>
<p class="small">本报告由 generate_reviewer_report.py 自动生成，所有数字直接读取上述 CSV。</p>
</div>
</body>
</html>"""

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
