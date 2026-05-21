<script setup lang="ts">
/**
 * Пример страницы модуля.
 * Использует usePortal() напрямую — все данные реактивны.
 * При смене компании в shell все refs обновятся автоматически.
 *
 * Для собственных данных используйте watch:
 *   watch(companyId, (newId) => { loadMyData(newId) })
 */
import { usePortal } from '../composables/usePortal'

const { user, company, branches, companyId, canManage } = usePortal()
</script>

<template>
  <div>
    <div class="mod-card">
      <div class="mod-card__title">Компания</div>
      <p v-if="company">{{ company.name }} ({{ company.timezone }})</p>
      <p v-else style="color:#9ca3af;">Не определена</p>
    </div>

    <div class="mod-card">
      <div class="mod-card__title">Текущий пользователь</div>
      <p>{{ user?.name }} — {{ user?.portal_role }}</p>
      <p style="font-size:12px;color:#8b8fa3;">
        canManage: {{ canManage() ? 'Да (может редактировать)' : 'Нет (только просмотр)' }}
      </p>
    </div>

    <div class="mod-card">
      <div class="mod-card__title">Филиалы ({{ branches.length }})</div>
      <table v-if="branches.length" class="mod-table">
        <thead><tr><th>Название</th><th>Адрес</th><th>Телефон</th></tr></thead>
        <tbody>
          <tr v-for="b in branches" :key="b.id">
            <td>{{ b.name }}</td>
            <td>{{ b.address || '—' }}</td>
            <td>{{ b.phone || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="mod-empty">Нет филиалов</div>
    </div>

    <div class="mod-card">
      <div class="mod-card__title">Действия</div>
      <button v-if="canManage()" class="mod-btn mod-btn--primary">
        <i data-feather="plus" style="width:14px;height:14px;"></i>
        Добавить
      </button>
      <p v-else style="color:#9ca3af;font-size:13px;">
        У вас нет прав на редактирование (canManage = false).
      </p>
    </div>
  </div>
</template>
