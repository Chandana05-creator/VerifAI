"""VerifAI — backend/services/export_service.py — Markdown and PDF versions of a report."""
from datetime import datetime

_PUNCT = {"—": "-", "–": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "...", "≥": ">=", "≤": "<=",
          "×": "x", "÷": "/", "·": "-", "•": "-", "→": "->", "✓": "+", "✗": "x"}


def _latin(s) -> str:
    """The built-in PDF fonts only support Latin-1, so replace anything else."""
    s = str(s or "")
    for k, v in _PUNCT.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def _pct(x) -> str:
    try:
        return f"{round(float(x) * 100)}%"
    except (TypeError, ValueError):
        return "-"


def _lean(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    return "left" if v < -20 else "right" if v > 20 else "centre"


def filename(kind: str, query: str, ext: str) -> str:
    base = "".join(c if c.isalnum() else "_" for c in (query or "report")[:40]).strip("_") or "report"
    return f"verifai_{'plagiarism' if kind == 'plagiarism' else 'report'}_{base}.{ext}"


# ───────────────────────── Markdown ─────────────────────────

def to_markdown(kind: str, query: str, created: str, report: dict, metrics: dict | None = None) -> str:
    out = []
    if kind == "plagiarism":
        out += ["# VerifAI plagiarism check", "", f"*Generated {created}*", "",
                f"**Originality:** {report.get('originality_percent')}%   |   **Similarity:** {report.get('similarity_percent')}%   |   **Risk:** {report.get('risk')}",
                "", f"Checked {report.get('passages_checked')} of {report.get('passages_total')} passages "
                f"({report.get('coverage_percent')}% of the words, {report.get('word_count')} words in total).", ""]
        out += ["## Matching sources", ""]
        for s in report.get("sources", []) or []:
            out.append(f"{s['n']}. [{s.get('title') or s['domain']}]({s['url']}) — {s['passages']} passage(s), "
                       f"up to {round(s['max_overlap'] * 100)}% overlap")
        if not report.get("sources"):
            out.append("No matching sources were found.")
        flagged = [g for g in report.get("segments", []) if g.get("status") in ("verbatim", "partial")]
        if flagged:
            out += ["", "## Flagged passages", ""]
            for g in flagged:
                out.append(f"> {g['text'].strip()}\n>\n> *{g['status']}, {round((g.get('score') or 0) * 100)}% overlap"
                           + (f", source [{g['source_n']}]" if g.get("source_n") else "") + "*\n")
        out += ["", f"*{report.get('disclaimer', '')}*"]
        return "\n".join(out)

    rel = report.get("reliability") or {}
    out += ["# VerifAI report", "", f"**Input:** {query}", "", f"*Generated {created}*", ""]
    if rel:
        out += [f"**Overall reliability:** {_pct(rel.get('score'))} — {rel.get('label', '')}", ""]
    out += ["## Summary", "", report.get("executive_summary", ""), ""]
    so = report.get("summary_originality")
    if so:
        out += [f"*Wording check: {so['verdict']} (highest overlap with a source: {so['max_overlap_pct']}%).*", ""]
    if report.get("key_findings"):
        out += ["## Key findings", ""]
        for k in report["key_findings"]:
            out.append(f"- {k.get('finding', '')} (confidence {_pct(k.get('confidence'))})")
        out.append("")
    if report.get("areas_of_uncertainty"):
        out += ["## Areas of uncertainty", ""]
        for k in report["areas_of_uncertainty"]:
            out.append(f"- **{k.get('topic', '')}** — {k.get('explanation', '')}")
        out.append("")
    out += ["## Claim verification", ""]
    for i, c in enumerate(report.get("all_claims", []), 1):
        out.append(f"{i}. **{c.get('verdict')}** ({_pct(c.get('confidence'))}) — {c.get('text')}")
        crit = c.get("critic")
        if crit:
            out.append(f"   - Critic challenge: **{crit['outcome']}** (confidence {_pct(crit['confidence_before'])} → {_pct(crit['confidence_after'])})")
        refs = c.get("evidence_refs", [])
        if refs:
            out.append("   - Evidence: " + ", ".join(f"[{r['n']}]({r['url']}) ({r['verdict'].lower()})" for r in refs))
    out.append("")
    scored = [s for s in report.get("source_scores", []) if "__fleet__" not in s]
    if scored:
        out += ["## Source credibility and bias", "", "| Source | Credibility | Political lean |", "|---|---|---|"]
        for s in scored:
            out.append(f"| {s.get('domain')} | {round(s.get('credibility', 0))}/100 | {s.get('lean_label', _lean(s.get('political_lean')))} |")
        out.append("")
    out += ["## Citations", ""]
    for it in report.get("citation_items", []) or []:
        out.append(f"{it['n']}. [{it['title']}]({it['url']}) — {it['domain']}")
    if metrics:
        out += ["", "## Run details", "",
                f"{metrics.get('total_seconds', 0)} s total · {metrics.get('llm_calls', 0)} model calls · "
                f"{metrics.get('tokens_in', 0) + metrics.get('tokens_out', 0)} tokens · {metrics.get('searches', 0)} searches"]
    return "\n".join(out)


# ───────────────────────── PDF ─────────────────────────

def to_pdf(kind: str, query: str, created: str, report: dict, metrics: dict | None = None) -> bytes:
    from fpdf import FPDF

    class Doc(FPDF):
        def footer(self):
            self.set_y(-12)
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(120, 120, 120)
            self.cell(0, 8, f"VerifAI - page {self.page_no()}", align="C")

    pdf = Doc(format="A4")
    pdf.set_auto_page_break(True, margin=16)
    pdf.set_margins(18, 16, 18)
    pdf.add_page()

    def para(text, size=10.5, style="", h=5.6, color=(30, 30, 30)):
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", style, size)
        pdf.set_text_color(*color)
        pdf.multi_cell(0, h, _latin(text), new_x="LMARGIN", new_y="NEXT")

    def head(text):
        pdf.ln(3)
        para(text, 13, "B", 7, (15, 118, 110))

    def link(label, url, prefix=""):
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(30, 30, 30)
        if prefix:
            pdf.write(5.4, _latin(prefix))
        pdf.set_text_color(5, 99, 193)
        pdf.set_font("Helvetica", "U", 10)
        pdf.write(5.4, _latin(label), link=url)
        pdf.ln(6)

    if kind == "plagiarism":
        para("VerifAI plagiarism check", 18, "B", 9)
        para(f"Generated {created}", 9, "I", color=(110, 110, 110))
        head("Result")
        para(f"Originality {report.get('originality_percent')}%  |  Similarity {report.get('similarity_percent')}%  |  Risk: {report.get('risk')}", 12, "B")
        para(f"Checked {report.get('passages_checked')} of {report.get('passages_total')} passages "
             f"({report.get('coverage_percent')}% of the {report.get('word_count')} words).")
        head("Matching sources")
        srcs = report.get("sources", []) or []
        for s in srcs:
            link(s.get("title") or s["domain"], s["url"], f"[{s['n']}] ")
            para(f"{s['passages']} passage(s), up to {round(s['max_overlap'] * 100)}% overlap", 9, "", 4.6, (100, 100, 100))
        if not srcs:
            para("No matching sources were found.")
        flagged = [g for g in report.get("segments", []) if g.get("status") in ("verbatim", "partial")]
        if flagged:
            head("Flagged passages")
            for g in flagged:
                para(f"({g['status']}, {round((g.get('score') or 0) * 100)}%"
                     + (f", source [{g['source_n']}]" if g.get("source_n") else "") + ")", 9, "B", 4.6, (160, 60, 20))
                para(g["text"].strip(), 10, "", 5)
        pdf.ln(3)
        para(report.get("disclaimer", ""), 8.5, "I", 4.4, (110, 110, 110))
        return bytes(pdf.output())

    rel = report.get("reliability") or {}
    para("VerifAI report", 18, "B", 9)
    para(f"Input: {query}", 10.5, "B")
    para(f"Generated {created}", 9, "I", color=(110, 110, 110))
    if rel:
        para(f"Overall reliability: {_pct(rel.get('score'))} - {rel.get('label', '')}", 12, "B", 7)
    head("Summary")
    para(report.get("executive_summary", ""))
    so = report.get("summary_originality")
    if so:
        para(f"Wording check: {so['verdict']} (highest overlap with a source: {so['max_overlap_pct']}%)", 8.5, "I", 4.4, (110, 110, 110))
    if report.get("key_findings"):
        head("Key findings")
        for k in report["key_findings"]:
            para(f"- {k.get('finding', '')} (confidence {_pct(k.get('confidence'))})")
    if report.get("areas_of_uncertainty"):
        head("Areas of uncertainty")
        for k in report["areas_of_uncertainty"]:
            para(f"- {k.get('topic', '')}: {k.get('explanation', '')}")
    head("Claim verification")
    for i, c in enumerate(report.get("all_claims", []), 1):
        para(f"{i}. {c.get('verdict')} ({_pct(c.get('confidence'))})", 10.5, "B")
        para(c.get("text", ""))
        crit = c.get("critic")
        if crit:
            para(f"Critic challenge: {crit['outcome']} (confidence {_pct(crit['confidence_before'])} -> {_pct(crit['confidence_after'])})", 9, "I", 4.6, (110, 110, 110))
        for r in c.get("evidence_refs", [])[:6]:
            link(f"[{r['n']}] {r['url'][:70]}", r["url"], f"   {r['verdict'].lower()}: ")
    scored = [s for s in report.get("source_scores", []) if "__fleet__" not in s]
    if scored:
        head("Source credibility and bias")
        for s in scored:
            para(f"{s.get('domain')}: credibility {round(s.get('credibility', 0))}/100, {s.get('lean_label', _lean(s.get('political_lean')))}")
    head("Citations")
    for it in report.get("citation_items", []) or []:
        link(it["title"][:80], it["url"], f"[{it['n']}] ")
    if metrics:
        head("Run details")
        para(f"{metrics.get('total_seconds', 0)} s total, {metrics.get('llm_calls', 0)} model calls, "
             f"{metrics.get('tokens_in', 0) + metrics.get('tokens_out', 0)} tokens, {metrics.get('searches', 0)} searches", 9.5)
    return bytes(pdf.output())
