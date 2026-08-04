/**
 * S2N Scanner - Finding Table Component
 */

import { useState } from 'react'
import { getFindingKey } from '@/types/scan'
import type { Finding } from '@/types/scan'

interface FindingTableProps {
    findings: Finding[]
}

export function FindingTable({ findings }: FindingTableProps) {
    const [selectedId, setSelectedId] = useState<string | null>(null)
    // 필터가 바뀌어 현재 findings에 없는 id를 가리키면 상세 패널은 자동으로 사라진다 (EXT-008).
    const selectedFinding = selectedId ? findings.find((f) => getFindingKey(f) === selectedId) ?? null : null

    if (findings.length === 0) {
        return (
            <div className="text-center p-8 text-muted-foreground bg-muted/20 border border-dashed rounded-lg">
                해당 조건의 취약점 내역이 없습니다.
            </div>
        )
    }

    const getSeverityColor = (severity: string) => {
        switch (severity.toUpperCase()) {
            case 'CRITICAL': return 'bg-red-100 text-red-800 border-red-200 dark:bg-red-900/30 dark:text-red-400 dark:border-red-800'
            case 'HIGH': return 'bg-orange-100 text-orange-800 border-orange-200 dark:bg-orange-900/30 dark:text-orange-400 dark:border-orange-800'
            case 'MEDIUM': return 'bg-yellow-100 text-yellow-800 border-yellow-200 dark:bg-yellow-900/30 dark:text-yellow-400 dark:border-yellow-800'
            case 'LOW': return 'bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-800'
            default: return 'bg-gray-100 text-gray-800 border-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:border-gray-700'
        }
    }

    return (
        <div className="flex flex-col md:flex-row gap-4 h-[600px]">
            {/* Table Area */}
            <div className={`overflow-y-auto border rounded-md shadow-sm bg-card flex-1 ${selectedFinding ? 'md:w-1/2' : 'w-full'}`}>
                <table className="w-full text-left text-sm">
                    <thead className="bg-muted sticky top-0 z-10 text-muted-foreground uppercase text-xs">
                        <tr>
                            <th className="px-4 py-3 font-medium">Severity</th>
                            <th className="px-4 py-3 font-medium">Plugin</th>
                            <th className="px-4 py-3 font-medium">Title</th>
                            <th className="px-4 py-3 font-medium hidden lg:table-cell">URL</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                        {findings.map((f) => (
                            <tr
                                key={getFindingKey(f)}
                                onClick={() => setSelectedId(getFindingKey(f))}
                                className={`hover:bg-accent/50 cursor-pointer transition-colors ${selectedId === getFindingKey(f) ? 'bg-accent/50' : ''}`}
                            >
                                <td className="px-4 py-3">
                                    <span className={`inline-block px-2 py-0.5 rounded text-xs font-semibold border ${getSeverityColor(f.severity)}`}>
                                        {f.severity}
                                    </span>
                                </td>
                                <td className="px-4 py-3 font-medium truncate max-w-[100px]">{f.plugin}</td>
                                <td className="px-4 py-3 truncate max-w-[200px]">{f.title}</td>
                                <td className="px-4 py-3 truncate max-w-[200px] hidden lg:table-cell text-muted-foreground">{f.url}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Detail Area */}
            {selectedFinding && (
                <div className="md:w-1/2 md:max-w-md lg:max-w-lg border rounded-md shadow-sm bg-card overflow-y-auto flex flex-col relative shrink-0">
                    <button
                        onClick={() => setSelectedId(null)}
                        className="absolute right-4 top-4 text-muted-foreground hover:text-foreground bg-secondary/80 rounded-full w-6 h-6 flex items-center justify-center p-0 text-lg leading-none"
                        aria-label="Close details"
                    >
                        ×
                    </button>
                    
                    <div className="p-6">
                        <div className="mb-4">
                            <span className={`inline-block px-2.5 py-1 rounded text-xs font-bold border mb-3 ${getSeverityColor(selectedFinding.severity)}`}>
                                {selectedFinding.severity}
                            </span>
                            <h3 className="text-xl font-bold leading-tight mb-2">{selectedFinding.title}</h3>
                            <p className="text-sm text-muted-foreground bg-muted p-3 rounded-md border mt-2 break-all">{selectedFinding.url}</p>
                        </div>
                        
                        <div className="space-y-6">
                            <div>
                                <h4 className="font-semibold text-sm uppercase tracking-wide border-b pb-1 mb-2">Description</h4>
                                <p className="text-sm text-card-foreground whitespace-pre-wrap">{selectedFinding.description}</p>
                            </div>

                            <div className="grid grid-cols-2 gap-4 text-sm bg-secondary/20 p-3 rounded-lg border">
                                {selectedFinding.plugin && <div><span className="text-muted-foreground block text-xs">Plugin</span> <span className="font-medium">{selectedFinding.plugin}</span></div>}
                                {selectedFinding.method && <div><span className="text-muted-foreground block text-xs">Method</span> <span className="font-medium">{selectedFinding.method}</span></div>}
                                {selectedFinding.parameter && <div><span className="text-muted-foreground block text-xs">Parameter</span> <span className="font-medium">{selectedFinding.parameter}</span></div>}
                                {selectedFinding.cweId && <div><span className="text-muted-foreground block text-xs">CWE ID</span> <span className="font-medium">{selectedFinding.cweId}</span></div>}
                                {selectedFinding.cvssScore !== undefined && <div><span className="text-muted-foreground block text-xs">CVSS</span> <span className="font-medium">{selectedFinding.cvssScore}</span></div>}
                            </div>

                            {selectedFinding.evidence && (
                                <div>
                                    <h4 className="font-semibold text-sm uppercase tracking-wide border-b pb-1 mb-2">Evidence</h4>
                                    <pre className="text-xs bg-zinc-950 text-emerald-400 p-4 rounded-md overflow-x-auto border">
                                        <code>{selectedFinding.evidence}</code>
                                    </pre>
                                </div>
                            )}

                            {selectedFinding.references.length > 0 && (
                                <div>
                                    <h4 className="font-semibold text-sm uppercase tracking-wide border-b pb-1 mb-2">References</h4>
                                    <div className="space-y-1">
                                        {selectedFinding.references.map((ref) => (
                                            <a key={ref} href={ref} target="_blank" rel="noreferrer" className="block text-sm text-blue-500 hover:underline break-all">
                                                {ref}
                                            </a>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
