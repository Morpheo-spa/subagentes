import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist', 'coverage', 'node_modules'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, ...globals.es2022 },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': 'off',
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      // Vetos del proyecto: sin axios, lodash, moment, redux, componentes de clase.
      'no-restricted-imports': [
        'error',
        {
          paths: [
            { name: 'axios', message: 'Prohibido: usa fetch a traves de src/lib/api.ts.' },
            { name: 'lodash', message: 'Prohibido: usa utilidades nativas.' },
            { name: 'lodash-es', message: 'Prohibido: usa utilidades nativas.' },
            { name: 'moment', message: 'Prohibido: usa Intl (src/lib/format.ts).' },
            { name: 'redux', message: 'Prohibido: TanStack Query + useState.' },
            { name: 'react-redux', message: 'Prohibido: TanStack Query + useState.' },
            { name: '@reduxjs/toolkit', message: 'Prohibido: TanStack Query + useState.' },
          ],
        },
      ],
      'no-restricted-syntax': [
        'error',
        {
          selector: "ClassDeclaration[superClass.name='Component']",
          message: 'Sin componentes de clase.',
        },
        {
          selector:
            "MemberExpression[object.name=/^(localStorage|sessionStorage)$/][property.name=/^(setItem|getItem)$/][parent.arguments.0.value=/token/i]",
          message: 'El access token vive solo en memoria.',
        },
      ],
    },
  },
  {
    files: ['src/components/ui/**/*.tsx'],
    rules: { '@typescript-eslint/no-explicit-any': 'off' },
  },
)
