import datetime as dt
import json
import os
import random
import re
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request

TOPIC_QUERIES = [
    "tidal sluice seepage fluctuating water level",
    "transient seepage hydraulic structure foundation uplift pressure",
    "periodic water head boundary pore pressure response soil",
    "fluctuating reservoir water level groundwater response foundation",
    "sluice foundation seepage uplift pressure",
    "unsteady seepage water level fluctuation hydraulic structure",
    "pore water pressure response cyclic water level seepage",
]

KEY_TERMS = [
    "sluice", "tidal", "seepage", "uplift", "foundation", "pore pressure",
    "water level", "fluctuation", "transient", "unsteady", "hydraulic structure",
    "head", "periodic", "reservoir", "groundwater",
]

FALLBACK_NOTES = [
    {
        "title": "周期水头边界下的幅值衰减与相位滞后",
        "body": "当外侧水位或脉动压力近似为周期边界时，地基内部压力水头通常不会同步等幅响应，而会表现为随传播距离增加的幅值衰减和相位滞后。对挡潮闸底板而言，测点越远离外河侧边界、渗透系数越低或储水效应越强，响应越可能滞后且幅值越小。",
        "keywords": "periodic head boundary; amplitude attenuation; phase lag; transient seepage",
    },
    {
        "title": "闸底板扬压力不是静水分布的简单缩放",
        "body": "在非稳定渗流中，底板下扬压力取决于边界水头变化、渗流路径、土层分布、排水条件和储水系数。潮位快速波动时，内部水头场可能处于过渡状态，某些位置会出现明显滞后，因此只按瞬时上下游水位差线性插值可能低估或高估局部扬压力。",
        "keywords": "uplift pressure; transient seepage; sluice floor; hydraulic gradient",
    },
]


def request_json(url, method="GET", data=None, token=None):
    headers = {
        "Accept": "application/vnd.github+json" if "api.github.com" in url else "application/json",
        "User-Agent": "seepage-daily-research-bot",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    body = None if data is None else json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def reconstruct_abstract(index):
    if not index:
        return ""
    positions = []
    for word, nums in index.items():
        for num in nums:
            positions.append((num, word))
    positions.sort()
    return " ".join(word for _, word in positions)


def clean_text(value):
    value = re.sub(r"\s+", " ", value or "").strip()
    return value


def sentence_excerpt(text, max_len=260):
    text = clean_text(text)
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?。！？])\s+", text)
    excerpt = parts[0]
    if len(excerpt) < 120 and len(parts) > 1:
        excerpt = f"{excerpt} {parts[1]}"
    return excerpt[:max_len].rstrip()


def authors_of(work):
    names = []
    for item in work.get("authorships", [])[:4]:
        author = item.get("author") or {}
        name = author.get("display_name")
        if name:
            names.append(name)
    if len(work.get("authorships", [])) > 4:
        names.append("等")
    return "、".join(names) or "作者信息待查"


def source_of(work):
    primary = work.get("primary_location") or {}
    source = primary.get("source") or {}
    return source.get("display_name") or "来源待查"


def link_of(work):
    doi = work.get("doi")
    if doi:
        return doi
    primary = work.get("primary_location") or {}
    return primary.get("landing_page_url") or work.get("id") or ""


def score_work(work):
    haystack = " ".join([
        work.get("title") or "",
        reconstruct_abstract(work.get("abstract_inverted_index")),
    ]).lower()
    score = sum(2 for term in KEY_TERMS if term in haystack)
    score += min(int(work.get("cited_by_count") or 0), 200) / 100.0
    year = work.get("publication_year") or 0
    if year >= 2015:
        score += 1
    if year >= 2020:
        score += 1
    return score


def fetch_candidates(today):
    query = TOPIC_QUERIES[today.toordinal() % len(TOPIC_QUERIES)]
    params = urllib.parse.urlencode({
        "search": query,
        "filter": "type:article,from_publication_date:2000-01-01",
        "sort": "cited_by_count:desc",
        "per-page": "25",
    })
    url = f"https://api.openalex.org/works?{params}"
    data = request_json(url)
    works = data.get("results", [])
    works = [w for w in works if w.get("title")]
    works.sort(key=score_work, reverse=True)
    return query, works


def existing_comment_texts(repo, issue_number, token):
    texts = []
    page = 1
    while True:
        url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments?per_page=100&page={page}"
        comments = request_json(url, token=token)
        if not comments:
            break
        texts.extend(c.get("body", "") for c in comments)
        if len(comments) < 100:
            break
        page += 1
    return "\n".join(texts)


def build_paper_note(work, query, today):
    title = clean_text(work.get("title"))
    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    excerpt = sentence_excerpt(abstract)
    year = work.get("publication_year") or "年份待查"
    source = source_of(work)
    link = link_of(work)
    cited = work.get("cited_by_count") or 0

    if excerpt:
        core_problem = f"论文摘要显示，其核心关注点可概括为：{excerpt}"
    else:
        core_problem = "从题名和来源看，这篇论文适合用于补充非稳定渗流、水位波动或地基压力水头响应方面的文献线索；建议进一步阅读全文核对模型边界和试验条件。"

    return textwrap.dedent(f"""
    ### {today:%Y-%m-%d} 每日推送：论文

    **{title}**

    - 作者：{authors_of(work)}
    - 来源：{source}，{year}
    - 链接：{link}
    - OpenAlex 引用数：{cited}

    **核心问题**  
    {core_problem}

    **和你的研究的连接**  
    这类研究可以放进“外侧水位/脉动压力边界 -> 闸基渗流场 -> 底板下压力水头响应”的分析框架中。阅读时建议重点看三件事：边界水头是否随时间变化，土体渗透系数和储水参数如何取值，内部测点水头是否出现幅值衰减或相位滞后。

    **今天可追问的建模点**  
    如果把潮位近似为周期水头边界，可以比较不同测点的响应幅值比和相位差；这些量比单个时刻的扬压力更能反映地基对脉动水压力的传递特性。

    **检索式**  
    `{query}`
    """).strip()


def build_fallback_note(today):
    note = FALLBACK_NOTES[today.toordinal() % len(FALLBACK_NOTES)]
    return textwrap.dedent(f"""
    ### {today:%Y-%m-%d} 每日推送：知识点

    **{note['title']}**

    {note['body']}

    **和你的研究的连接**  
    可把这个知识点用于解释挡潮闸外河侧潮位或脉动水压力传入闸基后，为什么底板下不同位置的测压管水头不会同步变化，也不会简单等比例变化。

    **检索式**  
    `{note['keywords']}`
    """).strip()


def post_comment(repo, issue_number, token, body):
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
    request_json(url, method="POST", data={"body": body}, token=token)


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    issue_number = os.environ.get("ISSUE_NUMBER", "1")
    token = os.environ["GITHUB_TOKEN"]
    today = dt.datetime.now().date()

    posted_text = existing_comment_texts(repo, issue_number, token)
    try:
        query, works = fetch_candidates(today)
        random.Random(today.isoformat()).shuffle(works[:8])
        selected = None
        for work in works:
            title = clean_text(work.get("title"))
            if title and title not in posted_text:
                selected = work
                break
        body = build_paper_note(selected, query, today) if selected else build_fallback_note(today)
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
        body = build_fallback_note(today) + f"\n\n_OpenAlex 检索暂时失败，已推送知识点。错误摘要：{type(exc).__name__}_"

    post_comment(repo, issue_number, token, body)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"daily research push failed: {exc}", file=sys.stderr)
        raise
