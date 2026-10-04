import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ExternalAnchor } from './ExternalAnchor'

export default function AssistantMarkdown({ text }: { text: string }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({ href, children, ...props }) => <ExternalAnchor {...props} href={href}>{children}</ExternalAnchor> }}>{text}</ReactMarkdown>
}
