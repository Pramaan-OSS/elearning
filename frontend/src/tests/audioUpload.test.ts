import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { Upload } from '@/utils/upload'

const tools: Upload[] = []
window.translatedMessages = {}
afterEach(() => { tools.forEach(t => t.destroy()); tools.length = 0; document.body.replaceChildren(); vi.restoreAllMocks() })
describe('audio lesson uploads', () => {
 it('renders a translated player and controls its own audio element', async () => {
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
  const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
  const render = (name: string) => {
   const tool = new Upload({ data: { file_url: `/private/files/${name}.wav`, file_type: 'WAV' }, readOnly: false })
   tools.push(tool);return tool.render()
  }
  const first = render('one'), second = render('two')
  document.body.append(first, second)
  first.normalize(); second.normalize()
  expect(first.querySelector('button')?.getAttribute('aria-label')).toBe('Play')
  expect(first.querySelector('source')?.getAttribute('type')).toBeNull()
  second.querySelector<HTMLButtonElement>('button')!.click()
  await nextTick()
  expect(play).toHaveBeenCalledTimes(1)
  expect(play.mock.contexts[0]).toBe(second.querySelector('audio'))
  expect(first.querySelector('button')?.getAttribute('aria-label')).toBe('Play')
  second.querySelector<HTMLButtonElement>('button')!.click()
  await nextTick()
  expect(pause.mock.contexts[0]).toBe(second.querySelector('audio'))
  second.querySelectorAll<HTMLButtonElement>('button')[1].click()
  await nextTick()
  expect(second.querySelector('audio')?.muted).toBe(true)
 })
})
