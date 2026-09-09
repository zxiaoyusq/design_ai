<script lang="ts">
import { defineComponent, h, type VNodeChild } from 'vue'

/** 只构造已知标签与文本节点，模型原文中的 HTML 永远不进入 innerHTML。 */
function inline(text: string): VNodeChild[] {
  const parts: VNodeChild[] = []
  const syntax = /\*\*(.+?)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^\s)]+)\)/g
  let offset = 0
  for (const match of text.matchAll(syntax)) {
    parts.push(text.slice(offset, match.index))
    if (match[1]) parts.push(h('strong', match[1]))
    else if (match[2]) parts.push(h('code', match[2]))
    else {
      // 外部链接仅允许 HTTP(S)，禁用脚本、数据地址和本地文件路径。
      const url = match[4] ?? ''
      parts.push(/^https?:\/\//i.test(url)
        ? h('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, match[3])
        : match[0])
    }
    offset = (match.index ?? 0) + match[0].length
  }
  parts.push(text.slice(offset))
  return parts
}

function blocks(text: string): VNodeChild[] {
  const nodes: VNodeChild[] = []
  let paragraph: string[] = []
  let items: VNodeChild[] = []
  let listKind = 'ul'
  let code: string[] | null = null
  const flushParagraph = () => {
    if (paragraph.length) nodes.push(h('p', inline(paragraph.join('\n'))))
    paragraph = []
  }
  const flushList = () => {
    if (items.length) nodes.push(h(listKind, items))
    items = []
  }
  for (const line of text.split('\n')) {
    if (/^\s*(```|~~~)/.test(line)) {
      flushParagraph(); flushList()
      if (code !== null) { nodes.push(h('pre', h('code', code.join('\n')))); code = null }
      else code = []
      continue
    }
    if (code !== null) { code.push(line); continue }
    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.+)$/)
    const item = line.match(/^\s*(?:([-+*])|\d+[.)])\s+(.+)$/)
    if (heading) {
      flushParagraph(); flushList()
      nodes.push(h(`h${Math.min(6, heading[1]!.length + 1)}`, inline(heading[2]!)))
    } else if (item) {
      flushParagraph()
      const kind = item[1] ? 'ul' : 'ol'
      if (kind !== listKind) flushList()
      listKind = kind
      items.push(h('li', inline(item[2]!)))
    } else if (line.startsWith('> ')) {
      flushParagraph(); flushList()
      nodes.push(h('blockquote', inline(line.slice(2))))
    } else if (!line.trim()) { flushParagraph(); flushList() }
    else { flushList(); paragraph.push(line) }
  }
  flushParagraph(); flushList()
  if (code !== null) nodes.push(h('pre', h('code', code.join('\n'))))
  return nodes
}

export default defineComponent({
  props: { text: { type: String, required: true } },
  setup: (props) => () => h('div', { class: 'safe-markdown' }, blocks(props.text)),
})
</script>

<style scoped>
.safe-markdown { color: #625d74; line-height: 1.85; font-size: 13px; overflow-wrap: anywhere; }
.safe-markdown :deep(p) { margin: 0 0 12px; white-space: pre-wrap; }
.safe-markdown :deep(h2), .safe-markdown :deep(h3), .safe-markdown :deep(h4), .safe-markdown :deep(h5), .safe-markdown :deep(h6) { margin: 20px 0 8px; color: #3c3557; font-size: 14px; }
.safe-markdown :deep(ul), .safe-markdown :deep(ol) { padding-left: 22px; margin: 8px 0 14px; }
.safe-markdown :deep(code) { padding: 2px 5px; background: #eeeaf6; border-radius: 4px; }
.safe-markdown :deep(pre) { padding: 12px; overflow: auto; background: #f4f1f8; border-radius: 8px; white-space: pre-wrap; }
.safe-markdown :deep(blockquote) { margin: 12px 0; padding-left: 14px; border-left: 3px solid #c4bbe9; }
</style>
