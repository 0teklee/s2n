import { useEffect, useState } from 'react'
import type { ScanHistoryItem } from '@/types/scan'
import { getScanHistory, deleteScanHistoryItem, clearScanHistory } from '@/lib/storage'
import { HistoryList } from './components/HistoryList'
import { ScanDetail } from './components/ScanDetail'
import { AiSettingsPanel } from './components/AiSettingsPanel'

export function OptionsApp() {
    const [history, setHistory] = useState<ScanHistoryItem[]>([])
    const [selectedScan, setSelectedScan] = useState<ScanHistoryItem | null>(null)
    const [isLoading, setIsLoading] = useState(true)
    const [activeTab, setActiveTab] = useState<'history' | 'settings'>('history')

    const loadHistory = async () => {
        try {
            const data = await getScanHistory()
            setHistory(data)
        } catch (error) {
            console.error('Failed to load history:', error)
        } finally {
            setIsLoading(false)
        }
    }

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect -- 마운트 시 1회성 데이터 로드
        loadHistory()
    }, [])

    const handleDelete = async (scanId: string) => {
        if (confirm('이 스캔 기록을 삭제하시겠습니까?')) {
            await deleteScanHistoryItem(scanId)
            setHistory(history.filter(h => h.scanId !== scanId))
        }
    }

    const handleClearAll = async () => {
        if (confirm('모든 스캔 히스토리를 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다.')) {
            await clearScanHistory()
            setHistory([])
            setSelectedScan(null)
        }
    }

    return (
        <div className="min-h-screen bg-background text-foreground p-8 font-sans">
            <header className="max-w-6xl mx-auto border-b pb-4 mb-6 flex justify-between items-end">
                <div>
                    <h1 className="text-2xl font-bold tracking-tight text-primary">S2N Scanner</h1>
                    <p className="text-sm text-muted-foreground mt-1">취약점 스캔 결과 리포트 및 설정</p>
                </div>
            </header>

            <main className="max-w-6xl mx-auto">
                <div className="flex space-x-2 mb-6 border-b pb-2">
                    <button 
                        className={`px-4 py-2 text-sm font-medium rounded-t-md transition-colors ${
                            activeTab === 'history' 
                                ? 'bg-secondary text-secondary-foreground border-b-2 border-primary' 
                                : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                        }`}
                        onClick={() => {
                            setActiveTab('history')
                            setSelectedScan(null)
                        }}
                    >
                        스캔 레포트 / 히스토리
                    </button>
                    <button 
                        className={`px-4 py-2 text-sm font-medium rounded-t-md transition-colors ${
                            activeTab === 'settings' 
                                ? 'bg-secondary text-secondary-foreground border-b-2 border-primary' 
                                : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                        }`}
                        onClick={() => {
                            setActiveTab('settings')
                            setSelectedScan(null)
                        }}
                    >
                        전역 설정
                    </button>
                </div>

                <div className="min-h-[500px]">
                    {isLoading ? (
                        <div className="flex items-center justify-center h-64 text-muted-foreground">
                            로딩 중...
                        </div>
                    ) : activeTab === 'history' ? (
                        selectedScan ? (
                            <ScanDetail 
                                scan={selectedScan} 
                                onBack={() => setSelectedScan(null)} 
                            />
                        ) : (
                            <div className="space-y-4">
                                <div className="flex justify-between items-center mb-4">
                                    <h2 className="text-lg font-semibold">최근 스캔 내역</h2>
                                    {history.length > 0 && (
                                        <button 
                                            onClick={handleClearAll}
                                            className="text-xs text-red-500 hover:text-red-600 hover:bg-red-50 px-2 py-1 rounded transition-colors"
                                        >
                                            전체 히스토리 초기화
                                        </button>
                                    )}
                                </div>
                                <HistoryList 
                                    history={history} 
                                    onSelectScan={setSelectedScan} 
                                    onDelete={handleDelete}
                                />
                            </div>
                        )
                    ) : (
                        <AiSettingsPanel />
                    )}
                </div>
            </main>
        </div>
    )
}
