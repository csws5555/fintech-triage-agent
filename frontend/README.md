# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR
and an ESLint flat configuration for TypeScript and React.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Linting

Run the repository lint baseline with:

```powershell
npm.cmd run lint
```

`eslint.config.js` applies the recommended JavaScript, TypeScript, React Hooks,
and Vite React Refresh rules to TypeScript source files. Generated `dist/`
output is ignored.
