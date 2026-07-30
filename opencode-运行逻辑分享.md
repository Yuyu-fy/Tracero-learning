# OpenCode 的运行逻辑：从一句需求到本地文件

这份文档用两个具体需求说明 OpenCode 如何工作：

1. 生成一个 `Hello World` 的 C++ 文件并保存到本地。
2. 在现有项目中编写并运行一个贪吃蛇游戏。

## 一句话概括

OpenCode 本身不是直接“写代码的模型”。它是运行在本机的编排程序：它把用户需求、项目上下文和可用工具交给选定的大模型；大模型决定要调用哪些工具；OpenCode 在本机检查权限后，真正读取文件、写入文件或执行命令。

```text
用户需求
  → OpenCode 组装上下文和工具
  → 调用选定的大模型
  → 模型请求调用工具
  → OpenCode 检查权限并在本机执行
  → 工具结果返回模型
  → 模型决定下一步，直到完成
```

## 参与者

| 参与者 | 主要职责 |
| --- | --- |
| 用户 | 描述目标，例如“写一个贪吃蛇”。 |
| OpenCode | 管理会话、上下文、权限、工具调用及结果。 |
| 大模型 | 理解目标、生成代码，并决定调用哪些工具。 |
| 本地文件系统 / 终端 | 实际保存文件、安装依赖、构建或运行项目。 |

## 常用工具

| 工具 | 含义 | 是否会改动本地文件 |
| --- | --- | --- |
| `glob` | 按路径模式查找文件名。 | 否 |
| `grep` | 在文件内容中搜索关键词。 | 否 |
| `read` | 读取文件内容。 | 否 |
| `write` | 创建文件或用完整内容覆盖文件。 | 是 |
| `edit` | 对现有文件做局部修改。 | 是 |
| `bash` | 在本机终端执行命令。 | 可能会 |

例如：

```text
glob("src/**/*.tsx")     # 找出 src 下所有 React 组件
grep("useState", "src") # 在 src 中查找 useState
```

其中，`*` 表示匹配当前目录的一段任意字符，`**` 表示可以跨越任意层级子目录。因此 `src/**/*.tsx` 会匹配 `src` 下及其所有子目录中的 TSX 文件。

---

## 示例一：生成并保存 Hello World C++

### 用户需求

```text
请生成一个 Hello World 的 C++ 程序，保存为 hello.cpp。
```

### 实际运行链路

```text
1. 用户提交提示词。
2. OpenCode 取得当前工作目录、会话记录、系统指令和工具定义。
3. OpenCode 将这些内容连同 write 工具的参数说明发送给当前选择的模型。
4. 模型生成 C++ 内容，并请求调用 write 工具。
5. OpenCode 计算文件改动 diff，并根据 edit 权限规则决定允许、询问或拒绝。
6. 若获得许可，OpenCode 在本机写入 hello.cpp。
7. OpenCode 可继续进行格式化和语言服务（LSP）诊断，并将结果展示给用户。
```

模型发出的工具调用在概念上类似：

```json
{
  "filePath": "/项目目录/hello.cpp",
  "content": "#include <iostream>\n\nint main() {\n  std::cout << \\\"Hello, World!\\n\\\";\n  return 0;\n}\n"
}
```

### OpenCode 的关键代码路径

```text
SessionPrompt.run()
  → SessionTools.resolve()
  → LLM.stream() / streamText()
  → 模型返回 write 工具调用
  → WriteTool.execute()
  → Permission.ask(permission: "edit")
  → fs.writeWithDirs(filepath, content)
```

`WriteTool.execute()` 的关键行为可以概括为：

```ts
const exists = yield* fs.existsSafe(filepath)
const source = exists ? yield* Bom.readFile(fs, filepath) : { bom: false, text: "" }
const diff = trimDiff(createTwoFilesPatch(filepath, filepath, source.text, contentNew))

yield* ctx.ask({
  permission: "edit",
  patterns: [path.relative(instance.worktree, filepath)],
  metadata: { filepath, diff },
})

yield* fs.writeWithDirs(filepath, contentNew)
```

这里真正把数据落到硬盘的是：

```ts
fs.writeWithDirs(filepath, contentNew)
```

模型只提出“请写入这个路径和内容”；真正拥有本地文件系统访问能力的是 OpenCode 进程。

---

## 示例二：编写并运行贪吃蛇游戏

### 用户需求

```text
请在这个项目中写一个可以在浏览器运行的贪吃蛇游戏，并运行它。
```

与 Hello World 的区别是：这通常不是一次写文件就结束，而是一个多轮的“模型决策 → 工具执行 → 返回结果 → 再决策”循环。

### 一次典型的工具调用序列

```text
1. glob("**/package.json")
   确认项目是否为 Node、Vite、React 等项目。

2. glob("src/**/*.{ts,tsx,js,jsx}")
   找到源代码目录及候选入口文件。

3. read("package.json")、read("src/App.tsx")
   读取依赖、脚本和现有代码结构。

4. write("src/SnakeGame.tsx", ...)
   创建贪吃蛇组件。

5. edit("src/App.tsx", ...)
   将贪吃蛇组件挂载到应用入口。

6. bash("npm run build")
   在本机进行构建验证。

7. 如果构建失败，模型读取报错内容，再调用 edit 或 write 修复代码。

8. bash("npm run dev")
   启动开发服务器；浏览器通过该服务器加载并执行游戏代码。
```

用流程图表示：

```text
“写一个贪吃蛇游戏”
          │
          ▼
模型先探索项目：glob / grep / read
          │
          ▼
模型生成或修改代码：write / edit
          │
          ▼
OpenCode 请求 edit 权限并写入本地磁盘
          │
          ▼
模型要求验证：bash("npm run build")
          │
     ┌────┴────┐
     │         │
   成功       失败
     │         │
     ▼         ▼
  启动服务   将报错返回模型 → 修改代码 → 再次构建
```

### 谁真正运行了游戏？

要区分三个阶段：

1. **模型生成游戏代码**：模型给出 HTML、CSS、JavaScript、React 或其他实现代码，并提出工具调用。
2. **OpenCode 写入和启动项目**：OpenCode 调用 `write`、`edit` 或 `bash`，在本机执行保存文件、`npm run build`、`npm run dev` 等操作。
3. **浏览器运行游戏**：若是 Web 贪吃蛇，最终实际执行游戏循环、键盘事件和画面渲染的是浏览器中的 JavaScript，而不是 OpenCode。

## 权限为什么重要

对于写入文件，`WriteTool.execute()` 会请求：

```ts
ctx.ask({
  permission: "edit",
  patterns: [目标文件路径],
})
```

对于终端命令，`bash` 工具也会经过对应的权限规则。规则通常有三种结果：

| 规则 | 结果 |
| --- | --- |
| `allow` | 直接执行。 |
| `ask` | 暂停并等待用户确认。 |
| `deny` | 拒绝执行。 |

因此，模型并不能绕过 OpenCode 任意修改电脑文件；本地 OpenCode 的权限配置和用户确认决定了工具调用是否真正执行。

## 结论

- Hello World 是一次或少数几次 `write` 工具调用：模型生成内容，OpenCode 经授权写入文件。
- 贪吃蛇是多轮 Agent 工作流：先探索项目，再编写代码，构建验证，根据结果修复，最后启动服务。
- `glob` 查找文件路径；`grep` 搜索文件内容；两者只读。
- `write`、`edit` 和 `bash` 才可能改变本地状态，并会受权限控制。
- 大模型负责“决定做什么”，OpenCode 负责“在本机安全地执行这些操作”。
