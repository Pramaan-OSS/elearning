import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Attendance from '@/components/Modals/LiveClassAttendance.vue'
import Cover from '@/components/Modals/EditCoverImage.vue'
const { call } = vi.hoisted(() => ({call: vi.fn()}))
vi.mock('frappe-ui', () => ({
 call,
 Dialog: {template: '<div><slot name="default" /></div>'},
 Button: {template: '<button><slot /></button>'},
 Popover: {template: '<div><slot /><slot name="default" /></div>'},
 FileUploader: {template: '<div />'},
}))
Object.defineProperty(String.prototype, 'format', {configurable:true, value: function(...args: unknown[]) {return String(this).replace(/\{(\d+)\}/g, (_, i) => String(args[Number(i)]))}})
const global = {mocks: {__: (s: string) => s}}
beforeEach(() => {call.mockReset()})
describe('adopted capability screens', () => {
 it('reports processing without claiming absence', async () => {
  call.mockResolvedValue({availability:'processing', results:[]})
  const w=mount(Attendance,{props:{modelValue:true,live_class:{name:'class'}},global})
  await flushPromises()
  expect(call).toHaveBeenCalledWith('lms.integrations.attendance.report',{live_class:'class'})
  expect(w.text()).toContain('still processing')
  expect(w.find('table').exists()).toBe(false)
  w.unmount()
 })
 it('shows completed sessions and plain refusal', async () => {
  call.mockResolvedValueOnce({availability:'available',results:[{name:'Learner',joinedAt:'2026-10-25T10:00:00Z',leftAt:'2026-10-25T10:30:00Z',durationSeconds:1800}]}).mockRejectedValueOnce(new Error())
  const w=mount(Attendance,{props:{modelValue:true,live_class:{name:'class'}},global})
  await flushPromises(); expect(w.text()).toContain('1800')
  await w.find('button').trigger('click'); await flushPromises()
  expect(w.text()).toContain('not available yet')
  expect(w.find('table').exists()).toBe(false)
  w.unmount()
 })
 it('keeps photo credit links and emits the selected photo', async () => {
  const photo={url:'https://images.test/a.jpg',previewUrl:'https://images.test/p.jpg',author:'Photographer',authorUrl:'https://source.test/author',sourceUrl:'https://source.test/photo',sourceCredit:'Photo library',sourceCreditUrl:'https://source.test',licence:'Stock licence',licenceUrl:'https://source.test/licence',attribution:'Photo by Photographer'}
  call.mockResolvedValue({results:[photo]})
  const w=mount(Cover,{global})
  await w.find('input').setValue('classroom'); await w.find('form').trigger('submit'); await flushPromises()
  expect(w.find(`a[href="${photo.authorUrl}"]`).text()).toBe('Photographer')
  expect(w.find(`a[href="${photo.sourceCreditUrl}"]`).text()).toBe('Photo library')
  await w.find('img').element.parentElement!.click()
  expect(w.emitted('select')?.[0]).toEqual([photo.url])
  w.unmount()
 })
})
