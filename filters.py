import logging
import os
import re
from hashlib import md5
from subprocess import PIPE, Popen
from dotenv import load_dotenv

from cairosvg import svg2png
from panflute import (BlockQuote, CodeBlock, Div, Doc, Element, Header, Image,
                      LineBreak, Para, RawBlock, RawInline, SoftBreak, Span,
                      Str, toJSONFilters)


load_dotenv()

# globals
LOG_FILE = os.getenv("LOG_FILE")
if LOG_FILE in (None, ''): LOG_FILE = "filters.log"

RESOURCE_PATH = os.getenv("RESOURCE_PATH")
if RESOURCE_PATH in (None, ''): RESOURCE_PATH = ''

ACTION_LIST = [
    "CONVERT_CALLOUT",
    "MAKE_LINEBREAKS",
    "MAKE_PAGEBREAKS",
    "CONVERT_SVG_TO_PNG",
    "CONVERT_MERMAID_TO_PNG",
    "RESIZE_IMAGES"
]

for i, action in enumerate(ACTION_LIST):
    val = os.getenv(action)
    if val in (None, '') or val.lower() in ('true', 'yes'): continue
    elif val.lower() in ('false', 'no'):
        ACTION_LIST.remove(action)
    else:
        raise ValueError(f"Invalid value for {action}: {val}")

CALLOUTS_MAP = {
    'note':     { 'icon': 'callout-icons/pencil.png',               'color': 'note'},
    'abstract': { 'icon': 'callout-icons/clipboard-list.png',       'color': 'abstract'},
    'info':     { 'icon': 'callout-icons/info.png',                 'color': 'info'},
    'todo':     { 'icon': 'callout-icons/check-circle-2.png',       'color': 'todo'},
    'tip':      { 'icon': 'callout-icons/flame.png',                'color': 'tip'},
    'success':  { 'icon': 'callout-icons/check.png',                'color': 'success'},
    'question': { 'icon': 'callout-icons/help-circle.png',          'color': 'question'},
    'warning':  { 'icon': 'callout-icons/alert-triangle.png',       'color': 'warning'},
    'failure':  { 'icon': 'callout-icons/x.png',                    'color': 'failure'},
    'danger':   { 'icon': 'callout-icons/zap.png',                  'color': 'danger'},
    'bug':      { 'icon': 'callout-icons/bug.png',                  'color': 'bug'},
    'example':  { 'icon': 'callout-icons/list.png',                 'color': 'example'},
    'quote':    { 'icon': 'callout-icons/quote.png',                'color': 'quote'},
}


# setup logger
LOGGER_NAME = "filter logger"
logger = logging.getLogger(LOGGER_NAME)
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('filters.log', mode='w')
formatter = logging.Formatter(fmt='%(asctime)s %(levelname)-8s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
fh.setFormatter(formatter)
logger.addHandler(fh)


def convert_callout(elem: Element, doc: Doc):
    callout_re = r'\[!.*?\]'
    if not (isinstance(elem, BlockQuote) and re.match(callout_re, elem.content[0].content[0].text)): return elem

    # get callout type
    callout_type = elem.content[0].content[0].text[2:-1]
    callout = CALLOUTS_MAP.get(callout_type, None)
    if callout is None: callout = CALLOUTS_MAP['note']

    # Remove the type from the first paragraph (removes the [!note] part)
    elem.content[0].content = elem.content[0].content[2:]

    # create the header for the callout
    include_image = r'\includegraphics[width=4mm,height=4mm]{' + callout['icon'] + r'} \hspace{2mm}'
    header = [RawInline(include_image, format='latex')]
    for el in elem.content[0].content:
        if isinstance(el, (LineBreak, SoftBreak)): break
        header.append(el)
    
    begin = RawBlock(r'\begin{tcolorbox}[width=\textwidth,boxrule=0pt,colback={' + callout['color'] + r'}]', format='latex')
    header = Header(*header, level=3)
    end = RawBlock(r'\end{tcolorbox}', format='latex')

    if len(header.content) - 1 == len(elem.content[0].content):
        return Div(begin, header, end)
    else:
        elem.content[0].content = elem.content[0].content[len(header.content):]
        return Div(begin, header, Div(*elem.content), end)


def convert_svg_to_png(elem: Element, doc: Doc):
    if not (isinstance(elem, Image) and elem.url.endswith(".svg")): return elem
    new_url = re.sub(".svg$", ".png", elem.url)
    
    if os.path.exists(elem.url):
        svg2png(open(elem.url, 'rb').read(), write_to=open(new_url, 'wb'), scale=3)
    elif os.path.exists(os.path.join(RESOURCE_PATH, elem.url)):
        svg2png(open(os.path.join(RESOURCE_PATH, elem.url), 'rb').read(), write_to=open(os.path.join(RESOURCE_PATH, new_url), 'wb'), scale=3)

    elem.url = new_url
    return Span(LineBreak, elem)


def convert_mermaid_to_png(elem: Element, doc: Doc):
    if not (isinstance(elem, CodeBlock) and elem.classes and elem.classes[0].startswith('mermaid')): return elem
    with open('temp.txt', 'w') as f:
        f.write(elem.text)

    my_hash = md5(elem.text.encode('utf-8')).hexdigest()
    img_title = 'mermaid-' + my_hash

    out_path = os.path.join(RESOURCE_PATH, img_title + '.png')
    command = ['type', 'temp.txt', '|', 'mmdc', '--input', '-', '-q', '-s', '2', '-o', f"{out_path}"]
    process = Popen(command, shell=True, stdout=PIPE, stderr=PIPE)
    process.wait()
    
    first_line = elem.text.splitlines()[0]
    matcher = re.match(r"^%% ?width:(.*)$", first_line)
    if matcher:
        img_title += f"|{matcher.group(1)}"

    return Para(Image(Str(img_title), url=out_path))


def resize_images(elem: Element, doc: Doc):
    if not (isinstance(elem, Image) and not len(elem.content) == 0): return elem
    img_title = elem.content[len(elem.content) - 1].text
    matcher = re.match(r".*\|(\d+)", img_title)
    if matcher: elem.attributes['width'] = matcher.group(1)
    return elem


def make_linebreaks(elem: Element, doc: Doc):
    if isinstance(elem, SoftBreak): return LineBreak()
    return elem


def make_pagebreaks(elem: Element, doc: Doc):
    if isinstance(elem, Div) and elem.attributes.get('style', None) == 'page-break-after: always;':
        return [RawBlock(r'\pagebreak', format='latex')]
    return elem


def get_elements(elem: Element, doc: Doc):
    logger.debug(f"get_elements: {elem}")
    logger.debug(f"type: {type(elem)}")


if __name__ == "__main__":
    logger.info("Starting filter")
    toJSONFilters([convert_callout, make_linebreaks, make_pagebreaks, convert_svg_to_png, convert_mermaid_to_png, resize_images])
    # toJSONFilters([make_linebreaks])
    # toJSONFilters([resize_images])
    # toJSONFilters([get_elements])
    logger.info("Finished filter")