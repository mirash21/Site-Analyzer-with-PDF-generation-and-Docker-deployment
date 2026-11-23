// Человекочитаемые названия разделов отчёта.
// Модель возвращает ключи JSON-схемы (brief_analysis, ad_examples, ...), а в
// интерфейсе они показывались как есть — «brief analysis». Здесь единственное
// место, где ключ превращается в заголовок раздела.
const LABELS = {
  brief_analysis: 'Краткий анализ сайта',
  analysis: 'Анализ сайта',
  ad_instructions: 'Инструкции по рекламным кампаниям',
  instructions: 'Инструкции',
  ad_examples: 'Примеры объявлений',
  examples: 'Примеры',
  target_audience: 'Целевая аудитория',
  audience: 'Аудитория',
  usp: 'Уникальные торговые предложения',
  strengths: 'Сильные стороны',
  weaknesses: 'Слабые стороны',
  recommendations: 'Рекомендации',
  comparison_table: 'Сравнительная таблица',
  key_facts: 'Ключевые факты и где их проверить',
  fact: 'Факт',
  source: 'Источник',
  page: 'Страница',
  sources: 'Прочитанные страницы',
  table: 'Таблица',
  title: 'Заголовок',
  heading: 'Заголовок',
  name: 'Название',
  body: 'Текст',
  text: 'Текст',
  content: 'Содержание',
  cta: 'Призыв к действию',
  call_to_action: 'Призыв к действию',
  button: 'Кнопка',
  channel: 'Канал',
  platform: 'Площадка',
  format: 'Формат',
  segments: 'Сегменты',
  product: 'Продукт',
  products: 'Продукты',
  benefit: 'Выгода',
  benefits: 'Выгоды',
  offline: 'Оффлайн',
  online: 'Онлайн',
  url: 'Адрес сайта',
  created_at: 'Дата анализа',
  steps: 'Шаги анализа',
  intermediate_results: 'Промежуточные результаты',
  final_analysis: 'Итоговый анализ',
}

export function labelFor(key) {
  if (typeof key !== 'string' || !key.trim()) return 'Раздел'
  const normalized = key.trim().replace(/[\s-]+/g, '_').toLowerCase()
  if (LABELS[normalized]) return LABELS[normalized]
  // Неизвестный ключ: «ad_examples_v2» -> «Ad examples v2» вместо «[object Object]».
  const spaced = normalized.replace(/_/g, ' ').trim()
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

export function formatDate(value) {
  if (!value) return 'не указана'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('ru-RU', {
    day: '2-digit',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
