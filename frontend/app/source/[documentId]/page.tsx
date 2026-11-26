import { SourceViewer } from './source-viewer';

export default async function SourcePage({ params, searchParams }: {
  params: Promise<{ documentId: string }>; searchParams: Promise<{ page?: string }>;
}) {
  const { documentId } = await params;
  const requested = Number((await searchParams).page ?? 1);
  const page = Number.isInteger(requested) && requested > 0 ? requested : 1;
  return <SourceViewer documentId={documentId} initialPage={page} />;
}
