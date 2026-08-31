/// <reference types="vite/client" />

interface InputEventTarget extends EventTarget {
  files: FileList | null
}

interface File {
  readonly webkitRelativePath: string
}
