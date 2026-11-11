"""Read-only browser geometry checks for the overview's human-readable labels.

This is supplemental to, not a replacement for, existing semantic/order/source,
state-protection and page-overflow assertions. It never alters the page or data.
"""

MEASURE_OVERVIEW = r'''() => {
    const root = document.querySelector('#vehicle-karte-overview');
    const rect = el => {
        const r = el.getBoundingClientRect();
        return {left:r.left, top:r.top, right:r.right, bottom:r.bottom, width:r.width, height:r.height};
    };
    const measureText = (el, directOnly=false) => {
        if (!el) throw new Error('Overview readability target missing');
        const nodes = [];
        if (directOnly) nodes.push(...[...el.childNodes].filter(n => n.nodeType === Node.TEXT_NODE));
        else {
            const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
            while (walker.nextNode()) nodes.push(walker.currentNode);
        }
        const boxes = [];
        for (const node of nodes) {
            const start = node.textContent.search(/\S/);
            if (start < 0) continue;
            const range = document.createRange();
            range.setStart(node, start); range.setEnd(node, node.textContent.trimEnd().length);
            boxes.push(...[...range.getClientRects()].filter(r => r.width > 0 && r.height > 0));
        }
        const tops = [];
        for (const b of boxes) if (!tops.some(top => Math.abs(top-b.top) < 2)) tops.push(b.top);
        const bounds = rect(el);
        return {text:nodes.map(n => n.textContent).join('').trim(), lines:tops.length, bounds,
            visible:el.checkVisibility({checkVisibilityCSS:true, checkOpacity:true}),
            contained:boxes.every(b => b.left >= bounds.left-1 && b.right <= bounds.right+1 &&
                b.top >= bounds.top-1 && b.bottom <= bounds.bottom+1),
            noOverflow:el.scrollWidth <= el.clientWidth+1 && el.scrollHeight <= el.clientHeight+1};
    };
    const summary = root.querySelector('.ko-work-summary');
    const header = root.querySelector('.ko-cost > .ko-heading');
    return {viewportWidth:innerWidth, rootWidth:root.getBoundingClientRect().width,
        summary:rect(summary), groups:[...summary.children].map(el => ({bounds:rect(el),
            label:measureText(el, true), count:measureText(el.querySelector('b'))})),
        workTitle:measureText(root.querySelector('#ko-work-title'), true),
        proposalTitle:measureText(root.querySelector('.ko-ai-heading'), true),
        costHeader:rect(header), costTitle:measureText(header.querySelector('h3'), true),
        period:measureText(header.querySelector('.ko-meta')), costLink:measureText(header.querySelector('a'))};
}'''


def validate_overview_readability(measurement):
    """Fail for compressed text even if document.scrollWidth still passes."""
    def require(condition, message):
        if not condition:
            raise AssertionError(f'Overview readability at {measurement["viewportWidth"]}px: {message}')

    def readable(item, name, max_lines=1):
        require(bool(item['text']), f'{name} is empty')
        require(item['visible'], f'{name} is hidden')
        require(1 <= item['lines'] <= max_lines, f'{name} wraps into {item["lines"]} lines (max {max_lines})')
        require(item['contained'] and item['noOverflow'], f'{name} is clipped or outside its box')

    groups = measurement['groups']
    require(len(groups) == 2, 'expected both summary groups')
    for group, label in zip(groups, ('未解消の対応', '予防整備の提案')):
        require(group['label']['text'] == label, f'{label} text changed')
        readable(group['label'], label)
        readable(group['count'], f'{label} count / previous-evaluation qualifier')
        b, parent = group['bounds'], measurement['summary']
        require(b['left'] >= parent['left']-1 and b['right'] <= parent['right']+1,
                f'{label} group exceeds summary width')
    for key in ('workTitle', 'proposalTitle', 'costTitle', 'costLink'):
        readable(measurement[key], key)
    readable(measurement['period'], 'cost period', max_lines=3)
    period, header = measurement['period']['bounds'], measurement['costHeader']
    require(period['width'] >= min(240, header['width'])-1, 'cost period has a narrow text column')
    require(period['left'] >= header['left']-1 and period['right'] <= header['right']+1,
            'cost period exceeds header width')
    if measurement['rootWidth'] <= 680:
        require(period['width'] >= header['width']-1, 'narrow cost period does not span the header')
        require(period['top'] >= max(measurement['costTitle']['bounds']['bottom'],
                                    measurement['costLink']['bounds']['bottom'])-1,
                'narrow cost period overlaps the title/link row')


def assert_overview_readability(page):
    measurement = page.evaluate(MEASURE_OVERVIEW)
    validate_overview_readability(measurement)
    return measurement
