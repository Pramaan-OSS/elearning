<template>
	<PageHeader :breadcrumbs="breadcrumbs" />
	<div class="mx-auto flex min-h-0 w-full max-w-5xl flex-1 flex-col p-5">
		<DataImport
			:doctype="param('doctype')"
			:importName="param('importName')"
			:doctypeMap="lmsPages"
		/>
	</div>
</template>
<script setup lang="ts">
import { usePageMeta } from 'frappe-ui'
import { DataImport } from '@framework/ui/components/DataImport/index'
import PageHeader from '@/components/Layouts/pages/PageHeader.vue'
import type { Breadcrumb } from '@/types'
import { sessionStore } from '../stores/session'
import { useRoute } from 'vue-router'
import { computed, inject, onMounted } from 'vue'
import { getLmsRoute } from '@/utils/basePath'

const { brand } = sessionStore()
const route = useRoute()
const user = inject<any>('$user')

// Both route segments are single dynamic params (routes.js), never repeated —
// narrowed here because vue-router types every param as `string | string[]`.
const param = (key: 'doctype' | 'importName') => {
	const value = route.params[key]
	return (Array.isArray(value) ? value[0] : value) || undefined
}

onMounted(() => {
	if (!user.data?.is_moderator) {
		window.location.href = getLmsRoute('courses')
	}
})

// Where an import's preview leads back to, as plain paths: the shared
// component navigates with the address bar, not the app's router.
const lmsPages: Record<
	string,
	{ title: string; listRoute?: string; pageRoute?: string }
> = {
	'LMS Course': {
		title: 'Courses',
		listRoute: getLmsRoute('courses'),
		pageRoute: `${getLmsRoute('courses')}/docname`,
	},
	'LMS Batch': {
		title: 'Batches',
		listRoute: getLmsRoute('batches'),
		pageRoute: `${getLmsRoute('batches')}/docname`,
	},
}

const breadcrumbs = computed<Breadcrumb[]>(() => {
	const crumbs: Breadcrumb[] = []
	crumbs.push({ label: __('Data Import'), route: { name: 'DataImportList' } })
	return crumbs
})

usePageMeta(() => {
	return {
		title: __('Data Import'),
		icon: brand.favicon,
	}
})
</script>
