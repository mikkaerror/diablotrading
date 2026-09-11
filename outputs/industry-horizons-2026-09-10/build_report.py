"""Create the PDF and inspectable evidence notebook from the frozen research."""
import contextlib
import html
import io
import json
import re
import runpy
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
md=(HERE/'research.md').read_text()
body,source_text=md.split('<!-- SOURCES -->')
sources={int(n):txt for n,txt in re.findall(r'^\[\^(\d+)\]: (.*)$',source_text,re.M)}
assert set(sources)==set(range(1,26))
ledger=[{'id':n,'citation':t,'urls':re.findall(r'\]\((https?://[^)]+)\)',t),'accessed':'2026-09-10'} for n,t in sources.items()]
(HERE/'sources.json').write_text(json.dumps(ledger,indent=2)+'\n')

styles={
 'title':ParagraphStyle('Title',fontName='Helvetica-Bold',fontSize=22,leading=26,spaceAfter=16),
 'h2':ParagraphStyle('Section',fontName='Helvetica-Bold',fontSize=14,leading=18,spaceBefore=5,spaceAfter=12,keepWithNext=True),
 'body':ParagraphStyle('Body',fontName='Helvetica',fontSize=10,leading=13.2,spaceAfter=8),
 'cell':ParagraphStyle('Cell',fontName='Helvetica',fontSize=8.7,leading=11.1,spaceAfter=0),
 'head':ParagraphStyle('Head',fontName='Helvetica-Bold',fontSize=8.7,leading=11.1,spaceAfter=0),
 'foot':ParagraphStyle('Footnote',fontName='Helvetica',fontSize=8,leading=10.3,spaceAfter=4),
 'source':ParagraphStyle('Source',fontName='Helvetica',fontSize=9.5,leading=13,spaceAfter=12),
}
def rich(s):
    s=html.escape(s)
    s=re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)',lambda m:'<a href="'+m[2]+'" color="#222222"><u>'+m[1]+'</u></a>',s)
    s=re.sub(r'\[\^(\d+)\]',r'<super>\1</super>',s)
    s=s.replace('</super><super>',',')
    s=re.sub(r'`([^`]+)`',r'<font name="Courier">\1</font>',s)
    return s
def paragraph(s,style='body'):
    return Paragraph(rich(s),styles[style])

def table(lines):
    data=[]
    for ln in lines:
        cells=[c.strip() for c in ln.strip().strip('|').split('|')]
        if all(re.fullmatch(r':?-+:?',c) for c in cells): continue
        data.append([paragraph(c,'head' if not data else 'cell') for c in cells])
    n=len(data[0]); widths=[130,160,214] if n==3 else [504/n]*n
    t=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#ececec')),
       ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),
       ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
       ('LINEBELOW',(0,0),(-1,0),.6,colors.HexColor('#777777')),
       ('LINEBELOW',(0,1),(-1,-1),.3,colors.HexColor('#cccccc'))]))
    return t

story=[]
sections=body.split('<!-- PAGE -->')
for idx,section in enumerate(sections):
    if idx: story.append(PageBreak())
    lines=section.strip().splitlines(); i=0
    while i<len(lines):
        line=lines[i].strip()
        if not line: i+=1;continue
        if line.startswith('|'):
            block=[]
            while i<len(lines) and lines[i].strip().startswith('|'):
                block.append(lines[i]);i+=1
            story.extend([table(block),Spacer(1,10)]);continue
        if line.startswith('# '): story.append(paragraph(line[2:],'title'))
        elif line.startswith('## '): story.append(paragraph(line[3:],'h2'))
        else: story.append(paragraph(line))
        i+=1
    refs=set(map(int,re.findall(r'\[\^(\d+)\]',section)))
    for nums in re.findall(r'\[(\d+(?:,\d+)*)\]',section): refs.update(map(int,nums.split(',')))
    if refs:
        story.append(Spacer(1,5))
        # Short numbered footnotes link directly to each original. Full citations follow.
        foot=[]
        for n in sorted(refs):
            text=sources[n]
            link=re.search(r'\[([^\]]+)\]\((https?://[^)]+)\)',text)
            label=text.split('. [')[0]
            if link: foot.append(f'{n}. <a href="{html.escape(link[2])}" color="#333333"><u>{html.escape(label)}</u></a>')
            else: foot.append(f'{n}. Frozen local coverage audit.')
        story.append(Paragraph(' &nbsp; '.join(foot),styles['foot']))

story.append(PageBreak());story.append(paragraph('Sources','h2'))
for n,txt in sources.items():
    if n==14:
        story.append(PageBreak());story.append(paragraph('Sources, continued','h2'))
    story.append(paragraph(str(n)+'. '+txt,'source'))
out=ROOT/'output/pdf/ai-infrastructure-industries-and-timelines.pdf'
out.parent.mkdir(parents=True,exist_ok=True)
doc=SimpleDocTemplate(str(out),pagesize=letter,rightMargin=54,leftMargin=54,topMargin=40,bottomMargin=36,
 title='AI Infrastructure: Industries, Investment Horizons, and Model Design',author='')
doc.build(story)

namespace=runpy.run_path(str(HERE/'profile.py'),run_name='research_audit')
stream=io.StringIO()
with contextlib.redirect_stdout(stream): namespace['profile']()
code='from pathlib import Path\nimport runpy\nreport_dir = Path.cwd()\nif not (report_dir / "profile.py").exists():\n    report_dir = report_dir / "outputs/industry-horizons-2026-09-10"\naudit = runpy.run_path(str(report_dir / "profile.py"), run_name="research_audit")\naudit["profile"]()\n'
notebook={'nbformat':4,'nbformat_minor':5,'metadata':{'kernelspec':{'name':'python3','display_name':'Python 3','language':'python'}},'cells':[
 {'cell_type':'markdown','metadata':{},'id':'scope','source':['# Frozen universe coverage audit\n','Run from this directory or the repository root. `profile.py` contains the complete checks. The cell reads the frozen research extracts, writes only the audit output, and makes no network or broker calls. Input hashes, periods and limitations are retained.']},
 {'cell_type':'code','metadata':{},'id':'audit','execution_count':1,'source':code.splitlines(keepends=True),'outputs':[{'output_type':'stream','name':'stdout','text':stream.getvalue().splitlines(keepends=True)}]}]}
(HERE/'coverage-audit.ipynb').write_text(json.dumps(notebook,indent=2)+'\n')
print(out)
print('Words:',len(body.split()),'sources:',len(sources))
