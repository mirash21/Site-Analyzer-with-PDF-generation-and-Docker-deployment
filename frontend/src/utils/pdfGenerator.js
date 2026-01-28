import jsPDF from 'jspdf'
import html2canvas from 'html2canvas'

/**
 * Генерация PDF из DOM элемента
 * @param {HTMLElement} element - DOM элемент для конвертации
 * @param {string} filename - Имя файла (будет преобразовано в транслит)
 * @param {Object} options - Дополнительные опции
 */
export async function generatePDF(element, filename = 'report', options = {}) {
  const {
    scale = 2, // Масштаб для лучшего качества
    margin = 10, // Отступы в мм
    format = 'a4', // Формат бумаги
    orientation = 'portrait' // Ориентация
  } = options

  try {
    // Клонируем элемент чтобы не изменять оригинал
    const clone = element.cloneNode(true)
    
    // Устанавливаем белый фон для лучшего качества PDF
    clone.style.background = 'white'
    clone.style.padding = '20px'
    
    // Создаем временный контейнер
    const container = document.createElement('div')
    container.style.position = 'fixed'
    container.style.left = '-9999px'
    container.style.top = '0'
    container.style.background = 'white'
    container.style.width = '210mm' // A4 ширина
    container.appendChild(clone)
    document.body.appendChild(container)

    // Генерируем canvas
    const canvas = await html2canvas(clone, {
      scale,
      useCORS: true,
      logging: false,
      backgroundColor: '#ffffff'
    })

    // Удаляем временный контейнер
    document.body.removeChild(container)

    // Получаем размеры
    const imgData = canvas.toDataURL('image/png')
    const imgWidth = 210 // A4 ширина в мм
    const imgHeight = (canvas.height * imgWidth) / canvas.width

    // Создаем PDF
    const pdf = new jsPDF(orientation, 'mm', format)
    
    // Добавляем заголовок с датой
    const date = new Date().toLocaleDateString('ru-RU', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
    
    pdf.setFontSize(10)
    pdf.setTextColor(128)
    pdf.text(`Дата экспорта: ${date}`, margin, margin)
    
    // Добавляем изображение
    let heightLeft = imgHeight
    let position = margin + 10

    // Добавляем первую страницу
    pdf.addImage(imgData, 'PNG', margin, position, imgWidth - 2 * margin, imgHeight - 2 * margin)
    heightLeft -= (imgHeight - 2 * margin)

    // Добавляем дополнительные страницы если нужно
    while (heightLeft > 0) {
      position = heightLeft - (imgHeight - 2 * margin)
      pdf.addPage()
      pdf.addImage(imgData, 'PNG', margin, position, imgWidth - 2 * margin, imgHeight - 2 * margin)
      heightLeft -= (imgHeight - 2 * margin)
    }

    // Транслитерация имени файла
    const transliteratedFilename = transliterate(filename) + '.pdf'
    
    // Сохраняем PDF
    pdf.save(transliteratedFilename)

    return { success: true, filename: transliteratedFilename }
  } catch (error) {
    console.error('Ошибка при генерации PDF:', error)
    return { success: false, error: error.message }
  }
}

/**
 * Транслитерация кириллицы в латиницу для имен файлов
 * @param {string} text - Текст для транслитерации
 * @returns {string} - Транслитерированный текст
 */
function transliterate(text) {
  const cyrillicToLatin = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch', 'ъ': '',
    'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'E',
    'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
    'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
    'Ф': 'F', 'Х': 'H', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Shch', 'Ъ': '',
    'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya', ' ': '_'
  }

  return text
    .split('')
    .map(char => cyrillicToLatin[char] || char)
    .join('')
    .replace(/[^a-zA-Z0-9_-]/g, '_')
    .replace(/_{2,}/g, '_')
    .replace(/^_|_$/g, '')
}

/**
 * Запрос имени файла у пользователя
 * @param {string} defaultName - Имя по умолчанию
 * @returns {string | null} - Введенное имя или null если отменено
 */
export function askFilename(defaultName = 'report') {
  const filename = prompt(
    'Введите имя файла для экспорта (опционально):',
    defaultName
  )
  
  if (filename === null) {
    return null // Пользователь нажал Отмена
  }
  
  return filename.trim() || defaultName
}

/**
 * Генерация PDF с запросом имени файла
 * @param {HTMLElement} element - DOM элемент для конвертации
 * @param {string} defaultFilename - Имя файла по умолчанию
 * @param {Object} options - Дополнительные опции
 */
export async function generatePDFWithPrompt(element, defaultFilename = 'report', options = {}) {
  const filename = askFilename(defaultFilename)
  
  if (filename === null) {
    return { success: false, cancelled: true }
  }
  
  return generatePDF(element, filename, options)
}
