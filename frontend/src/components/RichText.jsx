import { useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { labelFor } from '../utils/labels'

// Ответ модели приходит в markdown («# Заголовок», «- пункт», таблицы через «|»).
// Раньше этот текст выводился через whitespace-pre-wrap, поэтому разметка была
// видна как есть, а таблиц не существовало вовсе. Здесь markdown превращается
// в настоящую разметку. `code`-блоки и сырой HTML реакт-маркдаун экранирует,
// так что содержимое чужого сайта не может внедрить скрипты в отчёт.

const TAGS = {
  // Заголовки внутри ответа модели не должны перекрикивать заголовки страницы.
  h1: 'h4',
  h2: 'h4',
  h3: 'h5',
  h4: 'h5',
  h5: 'h6',
  h6: 'h6',
}

const classes = {
  h1: 'report-h report-h-lg',
  h2: 'report-h report-h-lg',
  h3: 'report-h report-h-md',
  h4: 'report-h report-h-md',
  h5: 'report-h report-h-sm',
  h6: 'report-h report-h-sm',
  p: 'report-p',
  ul: 'report-ul',
  ol: 'report-ol',
  li: 'report-li',
  a: 'report-a',
  strong: 'report-strong',
  em: 'report-em',
  blockquote: 'report-quote',
  hr: 'report-hr',
  code: 'report-code',
  pre: 'report-pre',
}

function heading(tag) {
  return function Heading({ node, children, ...props }) {
    const El = TAGS[tag] || 'h5'
    return <El className={classes[tag]} {...props}>{children}</El>
  }
}

// remark-gfm кладёт в DOM thead/tbody без обёртки; own-скролл нужен, чтобы
// широкая таблица не ломала вёрстку карточки.
function Table({ node, children, ...props }) {
  return (
    <div className="report-table-wrap">
      <table className="report-table" {...props}>{children}</table>
    </div>
  )
}

function Link({ node, href, children, ...props }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer nofollow"
      className={classes.a}
      {...props}
    >
      {children}
    </a>
  )
}

const markdownComponents = {
  h1: heading('h1'),
  h2: heading('h2'),
  h3: heading('h3'),
  h4: heading('h4'),
  h5: heading('h5'),
  h6: heading('h6'),
  p: ({ node, children, ...props }) => <p className={classes.p} {...props}>{children}</p>,
  ul: ({ node, children, ...props }) => <ul className={classes.ul} {...props}>{children}</ul>,
  ol: ({ node, children, ...props }) => <ol className={classes.ol} {...props}>{children}</ol>,
  li: ({ node, children, ...props }) => <li className={classes.li} {...props}>{children}</li>,
  strong: ({ node, children, ...props }) => <strong className={classes.strong} {...props}>{children}</strong>,
  em: ({ node, children, ...props }) => <em className={classes.em} {...props}>{children}</em>,
  blockquote: ({ node, children, ...props }) => <blockquote className={classes.blockquote} {...props}>{children}</blockquote>,
  hr: ({ node, ...props }) => <hr className={classes.hr} {...props} />,
  code: ({ node, className, children, ...props }) => (
    <code className={`${classes.code} ${className || ''}`} {...props}>{children}</code>
  ),
  pre: ({ node, children, ...props }) => <pre className={classes.pre} {...props}>{children}</pre>,
  table: Table,
  thead: ({ node, children, ...props }) => <thead className="report-thead">{children}</thead>,
  tbody: ({ node, children, ...props }) => <tbody {...props}>{children}</tbody>,
  tr: ({ node, children, ...props }) => <tr className="report-tr" {...props}>{children}</tr>,
  th: ({ node, children, ...props }) => <th className="report-th" {...props}>{children}</th>,
  td: ({ node, children, ...props }) => <td className="report-td" {...props}>{children}</td>,
  a: Link,
}

function isTableObject(value) {
  return Boolean(
    value &&
      !Array.isArray(value) &&
      Array.isArray(value.columns) &&
      Array.isArray(value.rows)
  )
}

const URL_LIKE = /^https?:\/\/\S+$/i

// Адрес из реестра источников должен открываться, а не переписываться глазами.
function MaybeLink({ value }) {
  if (typeof value === 'string' && URL_LIKE.test(value.trim())) {
    return (
      <a className={classes.a} href={value.trim()} target="_blank" rel="noopener noreferrer">
        {value.trim()}
      </a>
    )
  }
  return <RichText>{value}</RichText>
}

function pickTitle(value) {
  for (const key of ['title', 'heading', 'name', 'product', 'segment', 'fact']) {
    if (typeof value[key] === 'string' && value[key].trim()) return [key, value[key]]
  }
  return [null, null]
}

function TableView({ columns, rows }) {
  return (
    <div className="report-table-wrap">
      <table className="report-table">
        <thead className="report-thead">
          <tr>
            {columns.map((column, index) => (
              <th className="report-th" key={index}>{String(column ?? '')}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(rows || []).map((row, rowIndex) => {
            const cells = Array.isArray(row) ? row : Object.values(row || {})
            return (
              <tr className="report-tr" key={rowIndex}>
                {cells.map((cell, cellIndex) => (
                  <td className="report-td" key={cellIndex}>
                    {typeof cell === 'object' && cell !== null
                      ? String(cell)
                      : <MaybeLink value={cell ?? ''} />}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// Значения произвольной формы: списки, объекты, таблицы {columns, rows}.
function StructuredValue({ value, depth = 0 }) {
  if (value === null || value === undefined || value === '') {
    return <span className="report-empty">нет данных</span>
  }

  if (isTableObject(value)) {
    return <TableView columns={value.columns} rows={value.rows} />
  }

  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="report-empty">пусто</span>
    const allPrimitive = value.every((item) => typeof item !== 'object' || item === null)
    if (allPrimitive) {
      return (
        <ul className="report-ul">
          {value.map((item, index) => (
            <li className="report-li" key={index}>
              <RichText>{item}</RichText>
            </li>
          ))}
        </ul>
      )
    }
    return (
      <div className="report-cards">
        {value.map((item, index) => {
          const rest = { ...(item || {}) }
          const [titleKey, title] = pickTitle(rest)
          if (titleKey) delete rest[titleKey]
          return (
            <div className="report-card" key={index}>
              <p className="report-card-title">
                {title ? title : `Элемент ${index + 1}`}
              </p>
              <StructuredValue value={rest} depth={depth + 1} />
            </div>
          )
        })}
      </div>
    )
  }

  if (typeof value === 'object') {
    const entries = Object.entries(value)
    if (entries.length === 0) return <span className="report-empty">пусто</span>
    return (
      <dl className="report-dl">
        {entries.map(([key, item]) => (
          <div className="report-dl-row" key={key}>
            <dt className="report-dt">{labelFor(key)}</dt>
            <dd className="report-dd">
              {key === 'limit_note'
                ? <span className="report-warn">{String(item ?? '')}</span>
                : typeof item === 'string' || typeof item === 'number'
                  ? <MaybeLink value={item} />
                  : <StructuredValue value={item} depth={depth + 1} />}
            </dd>
          </div>
        ))}
      </dl>
    )
  }

  return <MaybeLink value={value} />
}

export default function RichText({ children, className = '' }) {
  if (children === null || children === undefined || children === '') return null
  if (typeof children === 'object') return <StructuredValue value={children} />

  const text = typeof children === 'string' ? children : String(children)
  return (
    <div className={`prose-report ${className}`}>
      <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {text}
      </Markdown>
    </div>
  )
}

// Семантику и минус-слова переносят в рекламный кабинет списком: фразы
// копируют целиком, а не переписывают по одной. Чипы — ещё и потому, что
// список из 25 фраз пунктами занимает экран, где полезнее разбор сайта.
export function KeywordList({ items }) {
  const [copied, setCopied] = useState(false)
  const phrases = (items || []).map((item) => String(item).trim()).filter(Boolean)
  if (!phrases.length) return <span className="report-empty">пусто</span>

  const copy = async () => {
    const text = phrases.join('\n')
    try {
      await navigator.clipboard.writeText(text)
    } catch (error) {
      // Clipboard API живёт только в защищённом контексте — на HTTP остаётся
      // временное поле и устаревшая команда копирования.
      const area = document.createElement('textarea')
      area.value = text
      document.body.appendChild(area)
      area.select()
      document.execCommand('copy')
      area.remove()
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="report-keywords">
      <div className="report-keyword-chips">
        {phrases.map((phrase, index) => (
          <span className="report-keyword" key={`${phrase}-${index}`}>{phrase}</span>
        ))}
      </div>
      <button type="button" className="report-copy no-print" onClick={copy}>
        {copied ? 'Скопировано' : 'Копировать список'}
      </button>
    </div>
  )
}

export { StructuredValue, TableView, isTableObject }
