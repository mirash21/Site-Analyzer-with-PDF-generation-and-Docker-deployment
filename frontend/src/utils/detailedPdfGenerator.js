import html2canvas from 'html2canvas'
import jsPDF from 'jspdf'

/**
 * Генерация профессионального PDF-отчета с поддержкой кириллицы
 * @param {Object} analysisData - Данные анализа (url, steps, intermediate_results, final_analysis)
 * @param {string} filename - Имя файла (будет преобразовано в транслит)
 */
export async function generateDetailedPDF(analysisData, filename = 'report') {
  try {
    // Создаем HTML-контейнер для отчета
    const container = document.createElement('div')
    container.style.position = 'fixed'
    container.style.left = '-9999px'
    container.style.top = '0'
    container.style.width = '170mm'
    container.style.background = 'white'
    container.style.padding = '20mm'
    container.style.fontFamily = 'Arial, "Helvetica Neue", Helvetica, sans-serif'
    container.style.fontSize = '11pt'
    container.style.color = '#333'
    container.style.lineHeight = '1.5'
    
    // Создаем HTML содержимое
    const htmlContent = generateReportHTML(analysisData)
    container.innerHTML = htmlContent
    
    document.body.appendChild(container)
    
    // Генерируем canvas с высоким разрешением для качественного PDF
    const canvas = await html2canvas(container, {
      scale: 3,
      useCORS: true,
      logging: false,
      backgroundColor: '#ffffff',
      letterRendering: true,
      allowTaint: true
    })
    
    // Удаляем временный контейнер
    document.body.removeChild(container)
    
    // Создаем PDF из canvas с поддержкой кириллицы через изображение
    const imgData = canvas.toDataURL('image/png', 1.0)
    const pdf = new jsPDF('p', 'mm', 'a4')
    
    const pdfWidth = pdf.internal.pageSize.getWidth()
    const pdfHeight = pdf.internal.pageSize.getHeight()
    
    // Рассчитываем размеры изображения для PDF
    const imgWidth = canvas.width
    const imgHeight = canvas.height
    const scaledImgHeight = pdfWidth * imgHeight / imgWidth
    
    // Добавляем первую страницу
    pdf.addImage(imgData, 'PNG', 0, 0, pdfWidth, scaledImgHeight)
    
    // Добавляем нумерацию страниц на первой странице
    addPageNumber(pdf, 1, 1, pdfHeight, pdfWidth)
    
    // Рассчитываем количество страниц
    const totalPages = Math.ceil(scaledImgHeight / pdfHeight)
    
    // Добавляем дополнительные страницы
    for (let i = 2; i <= totalPages; i++) {
      const position = -(i - 1) * pdfHeight
      pdf.addPage()
      pdf.addImage(imgData, 'PNG', 0, position, pdfWidth, scaledImgHeight)
      addPageNumber(pdf, i, totalPages, pdfHeight, pdfWidth)
    }
    
    // Сохраняем PDF
    const pdfFilename = transliterate(filename) + '.pdf'
    pdf.save(pdfFilename)
    
    return { success: true, filename: pdfFilename }
  } catch (error) {
    console.error('Ошибка при генерации PDF:', error)
    return { success: false, error: error.message }
  }
}

/**
 * Добавление нумерации страниц
 */
function addPageNumber(pdf, currentPage, totalPages, pageHeight, pageWidth) {
  // Используем латинские символы для совместимости
  const pageNumber = `Page ${currentPage} of ${totalPages}`
  pdf.setFontSize(9)
  pdf.setTextColor(128, 128, 128)
  pdf.text(pageNumber, pageWidth / 2, pageHeight - 10, { align: 'center' })
}

/**
 * Генерация HTML для отчета
 */
function generateReportHTML(data) {
  const date = new Date(data.created_at || Date.now()).toLocaleDateString('ru-RU', { 
    year: 'numeric', 
    month: 'long', 
    day: 'numeric',
    hour: '2-digit', 
    minute: '2-digit'
  })
  
  const stepsHTML = data.steps && data.steps.length > 0 
    ? data.steps.map((step, i) => `
        <div style="margin-bottom: 15px; padding: 10px; background: #f5f5f5; border-left: 3px solid #4f46e5; border-radius: 4px;">
          <div style="display: flex; align-items: center; margin-bottom: 8px;">
            <div style="width: 24px; height: 24px; background: #4f46e5; color: white; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; margin-right: 10px;">${i + 1}</div>
            <strong style="color: #4f46e5;">Шаг ${i + 1}</strong>
          </div>
          <p style="margin: 0; color: #555; line-height: 1.6;">${step}</p>
        </div>
      `).join('')
    : '<p style="color: #999; font-style: italic;">Нет данных о шагах анализа</p>'
  
  const intermediateHTML = data.intermediate_results && data.intermediate_results.length > 0
    ? data.intermediate_results.map(item => `
        <div style="margin-bottom: 20px; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden;">
          <div style="background: #f8f9fa; padding: 8px 12px; border-bottom: 1px solid #e0e0e0;">
            <strong style="color: #4f46e5; font-size: 11px;">Шаг ${item.step_number}: ${item.step}</strong>
          </div>
          <div style="padding: 12px; color: #555; line-height: 1.6; font-size: 11px;">
            ${item.result.split('\n').map(line => `<p style="margin: 0 0 6px 0;">${line}</p>`).join('')}
          </div>
        </div>
      `).join('')
    : '<p style="color: #999; font-style: italic;">Нет промежуточных результатов</p>'
  
  const finalAnalysisHTML = data.final_analysis
    ? Object.entries(data.final_analysis).map(([key, value]) => {
        const formattedKey = formatKey(key)
        
        let contentHTML = ''
        if (Array.isArray(value)) {
          contentHTML = value.map((item, i) => `
            <div style="background: #f0f4ff; padding: 8px 12px; border-radius: 6px; margin-bottom: 8px; font-size: 11px;">
              <strong style="color: #4f46e5;">${i + 1}.</strong> ${item}
            </div>
          `).join('')
        } else {
          contentHTML = `<p style="margin: 0; color: #555; line-height: 1.6; font-size: 11px;">${value}</p>`
        }
        
        return `
          <div style="margin-bottom: 20px;">
            <div style="background: #4f46e5; color: white; padding: 6px 12px; border-radius: 4px; margin-bottom: 10px;">
              <strong>${formattedKey}</strong>
            </div>
            ${contentHTML}
          </div>
        `
      }).join('')
    : '<p style="color: #999; font-style: italic;">Нет данных итогового анализа</p>'
  
  return `
    <div style="font-family: Arial, sans-serif; max-width: 1000px;">
      <!-- Заголовок -->
      <div style="text-align: center; margin-bottom: 30px; padding-bottom: 20px; border-bottom: 2px solid #4f46e5;">
        <h1 style="color: #4f46e5; margin: 0 0 15px 0; font-size: 24px;">ОТЧЕТ ОБ АНАЛИЗЕ ВЕБ-САЙТА</h1>
        <div style="font-size: 14px; color: #666; margin-bottom: 10px;">${date}</div>
        <div style="background: #f0f4ff; padding: 10px 20px; border-radius: 8px; display: inline-block;">
          <strong style="color: #4f46e5;">${data.url || 'Не указан'}</strong>
        </div>
      </div>

      <!-- Оглавление -->
      <div style="margin-bottom: 30px; padding: 15px; background: #f8f9fa; border-radius: 8px;">
        <h2 style="color: #4f46e5; margin: 0 0 15px 0; font-size: 16px;">Содержание</h2>
        <ul style="list-style: none; padding: 0; margin: 0;">
          <li style="padding: 6px 0; border-bottom: 1px solid #e0e0e0; display: flex; justify-content: space-between;">
            <span>1. Основная информация</span>
            <span>стр. 1</span>
          </li>
          <li style="padding: 6px 0; border-bottom: 1px solid #e0e0e0; display: flex; justify-content: space-between;">
            <span>2. Шаги анализа</span>
            <span>стр. 2</span>
          </li>
          <li style="padding: 6px 0; border-bottom: 1px solid #e0e0e0; display: flex; justify-content: space-between;">
            <span>3. Промежуточные результаты</span>
            <span>стр. 3</span>
          </li>
          <li style="padding: 6px 0; display: flex; justify-content: space-between;">
            <span>4. Итоговый анализ</span>
            <span>стр. 4</span>
          </li>
        </ul>
      </div>

      <!-- Раздел 1: Основная информация -->
      <div style="margin-bottom: 30px;">
        <h2 style="color: #4f46e5; margin: 0 0 15px 0; font-size: 16px; padding-bottom: 8px; border-bottom: 2px solid #4f46e5;">1. Основная информация</h2>
        <div style="background: #f8f9fa; padding: 15px; border-radius: 8px;">
          <p style="margin: 0 0 10px 0; color: #555;"><strong>URL сайта:</strong> ${data.url || 'Не указан'}</p>
          <p style="margin: 0 0 10px 0; color: #555;"><strong>Дата анализа:</strong> ${date}</p>
          <p style="margin: 0; color: #666; line-height: 1.6;">
            Данный отчет содержит подробный анализ веб-сайта, проведенный с помощью искусственного интеллекта.
            Включает все этапы анализа, промежуточные результаты и итоговые рекомендации.
          </p>
        </div>
      </div>

      <!-- Раздел 2: Шаги анализа -->
      <div style="margin-bottom: 30px; page-break-before: always;">
        <h2 style="color: #4f46e5; margin: 0 0 15px 0; font-size: 16px; padding-bottom: 8px; border-bottom: 2px solid #4f46e5;">2. Шаги анализа</h2>
        ${stepsHTML}
      </div>

      <!-- Раздел 3: Промежуточные результаты -->
      <div style="margin-bottom: 30px; page-break-before: always;">
        <h2 style="color: #4f46e5; margin: 0 0 15px 0; font-size: 16px; padding-bottom: 8px; border-bottom: 2px solid #4f46e5;">3. Промежуточные результаты</h2>
        ${intermediateHTML}
      </div>

      <!-- Раздел 4: Итоговый анализ -->
      <div style="margin-bottom: 30px; page-break-before: always;">
        <h2 style="color: #4f46e5; margin: 0 0 15px 0; font-size: 16px; padding-bottom: 8px; border-bottom: 2px solid #4f46e5;">4. Итоговый анализ</h2>
        ${finalAnalysisHTML}
      </div>

      <!-- Футер -->
      <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #e0e0e0; text-align: center; color: #999; font-size: 11px;">
        Сгенерировано автоматически с помощью AI-анализатора • ${date}
      </div>
    </div>
  `
}

/**
 * Форматирование ключа
 */
function formatKey(key) {
  return key
    .replace(/_/g, ' ')
    .replace(/([A-Z])/g, ' $1')
    .replace(/^\s/, '')
    .split(' ')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ')
}

/**
 * Транслитерация кириллицы в латиницу для имен файлов
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
 */
export function askFilename(defaultName = 'report') {
  const filename = prompt(
    'Введите имя файла для экспорта (опционально):',
    defaultName
  )
  
  if (filename === null) {
    return null
  }
  
  return filename.trim() || defaultName
}

/**
 * Генерация PDF с запросом имени файла
 */
export async function generateDetailedPDFWithPrompt(analysisData, defaultFilename = 'report') {
  const filename = askFilename(defaultFilename)
  
  if (filename === null) {
    return { success: false, cancelled: true }
  }
  
  return generateDetailedPDF(analysisData, filename)
}
