<template>
	<Dialog
		v-model:open="show"
		:title="__('Attendance for Class - {0}').format(live_class?.title)"
		size="4xl"
	>
        <template #default>
            <p>{{ __('Not yet live-verified. Display names are not verified learner identities.') }}</p>
            <Button @click="load" :loading="loading">{{ __('Refresh attendance') }}</Button>
            <p role="alert">{{ message }}</p>
            <table v-if="rows.length" class="w-full text-sm">
                <thead><tr><th>{{ __('Participant name') }}</th><th>{{ __('Joined at') }}</th><th>{{ __('Left at') }}</th><th>{{ __('Seconds attended') }}</th></tr></thead>
                <tbody><tr v-for="(row, index) in rows" :key="index"><td>{{ row.name }}</td><td>{{ row.joinedAt }}</td><td>{{ row.leftAt }}</td><td>{{ row.durationSeconds }}</td></tr></tbody>
            </table>
		</template>
	</Dialog>
</template>
<script setup>
import { Button, call, Dialog } from 'frappe-ui'
import { ref, watch } from 'vue'
const show = defineModel()
const props = defineProps({live_class: Object})
const rows = ref([])
const loading = ref(false)
const message = ref('')
const load = async () => {
 if (!props.live_class?.name) return
 rows.value = []; loading.value = true; message.value = ''
 try {
  const report = await call('lms.integrations.attendance.report', {live_class: props.live_class.name})
  rows.value = report.results
  message.value = report.availability === 'processing' ? __('Attendance is still processing. Try after the class ends.') : report.availability === 'no_data' ? __('No attendance data is available. This does not mean nobody attended.') : !rows.value.length ? __('The report contains no completed sessions.') : ''
 } catch {message.value = __('Attendance is not available yet, or you do not have access.')}
 finally {loading.value = false}
}
watch(() => [show.value, props.live_class?.name], () => {if(show.value) load()}, {immediate: true})
</script>
