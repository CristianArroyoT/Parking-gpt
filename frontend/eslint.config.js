// Configuración plana de ESLint 9 (frontend de solidAPP).
//
// POR QUÉ este fichero existe (2026-10-22): el ``package.json`` tenía un
// script ``lint`` (``eslint --ext .ts,.vue src``) que **nunca funcionó**:
// ESLint 9 exige un ``eslint.config.js`` (config plano) y en el repo no
// había ninguno. El job de frontend del CI tampoco lo ejecutaba, así que
// el linter roto pasó desapercibido.
//
// Con este fichero, ``npm run lint`` es una puerta real: el CI la ejecuta
// (job ``frontend``).
//
// La configuración recomendada para Vue 3 + TypeScript es la de
// ``@vue/eslint-config-typescript``: reglas de Vue (flat/recommended) +
// reglas de TypeScript sin las que se solapan.
import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'

export default defineConfigWithVueTs(
  {
    ignores: ['dist/**', 'node_modules/**', 'coverage/**', 'scripts/**'],
  },
  js.configs.recommended,
  // ``flat/essential`` y no ``flat/recommended``: "recommended" arrastra
  // reglas de FORMATO (una etiqueta por línea, un atributo por línea…) que
  // son opinión y que obligarían a reformatear el frontend entero. Con
  // "essential" el linter avisa de lo que está **mal** (variables sin
  // usar, referencias sin definir, hooks mal usados), no de lo que está
  // escrito de otra manera.
  pluginVue.configs['flat/essential'],
  vueTsConfigs.recommended,
  {
    rules: {
      // Los nombres de los componentes de una sola palabra (Login, Home)
      // son la convención del proyecto, no un error.
      'vue/multi-word-component-names': 'off',
      // Los `defineProps` con tipo inferred de los SFC de Vue son
      // correctos; el error viene de la regla de `no-undef` sobre los
      // macros del compilador.
      'vue/no-undef-properties': 'off',
    },
  },
  {
    // Los ficheros de declaración (``.d.ts``) llevan el shim estándar de
    // Vue (``DefineComponent<{}, {}, any>``) y los ``interface`` vacíos de
    // Vite. El ``{}`` de ahí es intencionado, así que la regla que lo
    // señala se apaga **sólo** en estos ficheros.
    files: ['**/*.d.ts'],
    rules: {
      '@typescript-eslint/no-empty-object-type': 'off',
    },
  },
)
