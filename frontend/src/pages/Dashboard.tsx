import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { crmService } from '../services/api';
import type { Contact, GmailOAuthStatusResponse, Nudge, PendingEmailDraft, SegmentGroup, PipelineInsightsResponse, VoiceMemoResponse } from '../services/api';
import { Target, TrendingUp, Users, Phone, Mail, ArrowRight, RefreshCw, AlertTriangle, Zap, Flame, Snowflake, Moon, Mic, Send, Square } from 'lucide-react';
import './Dashboard.css';

type SpeechRecognitionResultLike = {
    isFinal: boolean;
    0?: {
        transcript?: string;
    };
};

type SpeechRecognitionEventLike = Event & {
    resultIndex: number;
    results: {
        length: number;
        [index: number]: SpeechRecognitionResultLike;
    };
};

type SpeechRecognitionErrorLike = Event & {
    error?: string;
    message?: string;
};

type SpeechRecognitionLike = {
    continuous: boolean;
    interimResults: boolean;
    lang: string;
    onstart: (() => void) | null;
    onresult: ((event: SpeechRecognitionEventLike) => void) | null;
    onerror: ((event: SpeechRecognitionErrorLike) => void) | null;
    onend: (() => void) | null;
    abort: () => void;
    start: () => void;
    stop: () => void;
};

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

type VoiceMemoExtractedData = {
    areas?: string[];
    budget?: number | string;
    likes?: string[];
    dislikes?: string[];
};

type NudgeActionPresentation = {
    label: string;
    message: (nudge: Nudge) => string;
};

declare global {
    interface Window {
        SpeechRecognition?: SpeechRecognitionConstructor;
        webkitSpeechRecognition?: SpeechRecognitionConstructor;
    }
}

const Dashboard = () => {
    const [contacts, setContacts] = useState<Contact[]>([]);
    const [nudges, setNudges] = useState<Nudge[]>([]);
    const [segments, setSegments] = useState<SegmentGroup[]>([]);
    const [insights, setInsights] = useState<PipelineInsightsResponse | null>(null);
    const [gmailStatus, setGmailStatus] = useState<GmailOAuthStatusResponse | null>(null);
    const [pendingEmailDrafts, setPendingEmailDrafts] = useState<PendingEmailDraft[]>([]);
    const [loading, setLoading] = useState(true);
    const [emailReviewAction, setEmailReviewAction] = useState<Record<number, string>>({});
    const [emailReviewFeedback, setEmailReviewFeedback] = useState('');

    // Voice memo state
    const [memoText, setMemoText] = useState('');
    const [memoProcessing, setMemoProcessing] = useState(false);
    const [memoResult, setMemoResult] = useState<VoiceMemoResponse | null>(null);
    const [voiceListening, setVoiceListening] = useState(false);
    const [recorderSupported, setRecorderSupported] = useState(true);
    const [voiceDraft, setVoiceDraft] = useState('');
    const [voiceError, setVoiceError] = useState('');
    const [recordingUrl, setRecordingUrl] = useState('');
    const [recordingSeconds, setRecordingSeconds] = useState(0);
    const [recordingMimeType, setRecordingMimeType] = useState('');
    const [transcribingAudio, setTranscribingAudio] = useState(false);
    const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
    const mediaRecorderRef = useRef<MediaRecorder | null>(null);
    const mediaStreamRef = useRef<MediaStream | null>(null);
    const recordingChunksRef = useRef<Blob[]>([]);
    const recordingTimerRef = useRef<ReturnType<typeof window.setInterval> | null>(null);
    const recordingUrlRef = useRef('');
    const memoTextRef = useRef('');

    const loadAll = async () => {
        setLoading(true);
        try {
            const [contactsData, nudgesData, segmentsData, insightsData, gmailStatusData, pendingEmailDraftsData] = await Promise.all([
                crmService.getContacts(),
                crmService.getNudges(),
                crmService.getSegments(),
                crmService.getPipelineInsights(),
                crmService.getGmailStatus(),
                crmService.getPendingEmailDrafts(),
            ]);
            setContacts(contactsData);
            setNudges(nudgesData.nudges);
            setSegments(segmentsData.segments);
            setInsights(insightsData);
            setGmailStatus(gmailStatusData);
            setPendingEmailDrafts(pendingEmailDraftsData.drafts);
        } catch (error) {
            console.error('Failed to load dashboard:', error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadAll();
    }, []);

    useEffect(() => {
        memoTextRef.current = memoText;
    }, [memoText]);

    useEffect(() => {
        setRecorderSupported(
            'mediaDevices' in navigator
            && typeof navigator.mediaDevices?.getUserMedia === 'function'
            && 'MediaRecorder' in window
        );

        return () => {
            recognitionRef.current?.abort();
            recognitionRef.current = null;
            if (mediaRecorderRef.current?.state === 'recording') {
                mediaRecorderRef.current.stop();
            }
            mediaRecorderRef.current = null;
            mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
            mediaStreamRef.current = null;
            if (recordingTimerRef.current) {
                window.clearInterval(recordingTimerRef.current);
                recordingTimerRef.current = null;
            }
            if (recordingUrlRef.current) {
                URL.revokeObjectURL(recordingUrlRef.current);
                recordingUrlRef.current = '';
            }
        };
    }, []);

    const getRecognitionConstructor = () => window.SpeechRecognition || window.webkitSpeechRecognition;

    const appendMemoTranscript = (transcript: string) => {
        const cleanTranscript = transcript.trim();
        if (!cleanTranscript) return;

        setMemoText((current) => {
            const separator = current.trim() ? ' ' : '';
            return `${current}${separator}${cleanTranscript}`;
        });
    };

    const stopRecordingTimer = () => {
        if (recordingTimerRef.current) {
            window.clearInterval(recordingTimerRef.current);
            recordingTimerRef.current = null;
        }
    };

    const stopMediaStream = () => {
        mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
        mediaStreamRef.current = null;
    };

    const clearRecording = () => {
        if (recordingUrlRef.current) {
            URL.revokeObjectURL(recordingUrlRef.current);
            recordingUrlRef.current = '';
        }
        setRecordingUrl('');
        setRecordingMimeType('');
        setRecordingSeconds(0);
    };

    const formatRecordingTime = (seconds: number) => {
        const minutes = Math.floor(seconds / 60).toString().padStart(2, '0');
        const remainingSeconds = (seconds % 60).toString().padStart(2, '0');
        return `${minutes}:${remainingSeconds}`;
    };

    const startSpeechRecognition = () => {
        const SpeechRecognition = getRecognitionConstructor();

        if (!SpeechRecognition) {
            setVoiceError('正在錄音，但這個瀏覽器沒有即時語音轉文字。停止後可播放錄音；要進行 Analyze，請把重點補到文字框。');
            return;
        }

        try {
            recognitionRef.current?.abort();
            const recognition = new SpeechRecognition();
            recognition.continuous = true;
            recognition.interimResults = true;
            recognition.lang = 'zh-TW';

            recognition.onstart = () => {
                setVoiceDraft('');
            };

            recognition.onresult = (event) => {
                let finalTranscript = '';
                let interimTranscript = '';

                for (let i = event.resultIndex; i < event.results.length; i += 1) {
                    const result = event.results[i];
                    const transcript = result[0]?.transcript ?? '';

                    if (result.isFinal) {
                        finalTranscript += transcript;
                    } else {
                        interimTranscript += transcript;
                    }
                }

                appendMemoTranscript(finalTranscript);
                setVoiceDraft(interimTranscript.trim());
            };

            recognition.onerror = (event) => {
                const message = event.error === 'not-allowed'
                    ? '錄音已啟動，但語音轉文字權限被拒絕。請允許麥克風權限，或停止後播放錄音再手動補文字。'
                    : event.error === 'no-speech'
                        ? '錄音中，但暫時沒有偵測到可轉文字的語音。'
                        : '錄音中，但即時語音轉文字暫時無法使用。停止後可播放錄音，再手動補文字。';

                setVoiceError(message);
                setVoiceDraft('');
            };

            recognition.onend = () => {
                recognitionRef.current = null;
                setVoiceDraft('');
            };

            recognitionRef.current = recognition;
            recognition.start();
        } catch (error) {
            console.error('Failed to start speech recognition:', error);
            setVoiceError('錄音已啟動，但即時語音轉文字無法啟動。停止後可播放錄音，再手動補文字。');
        }
    };

    const stopVoiceInput = () => {
        recognitionRef.current?.stop();
        if (mediaRecorderRef.current?.state === 'recording') {
            mediaRecorderRef.current.stop();
        } else {
            stopRecordingTimer();
            stopMediaStream();
        }
        setVoiceListening(false);
        setVoiceDraft('');
    };

    const startVoiceInput = async () => {
        setVoiceError('');
        setMemoResult(null);
        clearRecording();

        if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
            setRecorderSupported(false);
            setVoiceError('這個瀏覽器目前沒有開放麥克風錄音功能。請用 Chrome 開啟同一個網址，或先貼上語音轉文字內容。');
            return;
        }

        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaStreamRef.current = stream;
            recordingChunksRef.current = [];

            const recorder = new MediaRecorder(stream);
            mediaRecorderRef.current = recorder;
            setRecorderSupported(true);
            setRecordingMimeType(recorder.mimeType || 'audio/webm');

            recorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    recordingChunksRef.current.push(event.data);
                }
            };

            recorder.onstop = () => {
                stopRecordingTimer();
                stopMediaStream();
                mediaRecorderRef.current = null;
                setVoiceListening(false);
                setVoiceDraft('');

                const audioBlob = new Blob(recordingChunksRef.current, { type: recorder.mimeType || 'audio/webm' });
                recordingChunksRef.current = [];

                if (audioBlob.size > 0) {
                    const objectUrl = URL.createObjectURL(audioBlob);
                    recordingUrlRef.current = objectUrl;
                    setRecordingUrl(objectUrl);
                    setVoiceError('錄音已完成，正在用本機 Whisper 轉成文字...');
                    setTranscribingAudio(true);
                    crmService.transcribeVoiceMemoAudio(audioBlob, 'voice-memo.webm')
                        .then((transcription) => {
                            if (transcription.success && transcription.text.trim()) {
                                appendMemoTranscript(transcription.text);
                                setVoiceError('轉錄完成。請檢查文字內容，確認後按 Analyze & Save 存成或更新 lead。');
                                return;
                            }

                            setVoiceError(transcription.message || '沒有轉出文字，請播放錄音後手動補上重點，再按 Analyze & Save。');
                        })
                        .catch((error) => {
                            console.error('Voice memo transcription failed:', error);
                            setVoiceError('本機轉錄失敗。請播放錄音後手動補上重點，再按 Analyze & Save。');
                        })
                        .finally(() => {
                            setTranscribingAudio(false);
                        });
                }
            };

            recorder.start();
            setVoiceListening(true);
            setRecordingSeconds(0);
            recordingTimerRef.current = window.setInterval(() => {
                setRecordingSeconds((current) => current + 1);
            }, 1000);
            startSpeechRecognition();
        } catch (error) {
            console.error('Failed to start audio recording:', error);
            stopRecordingTimer();
            stopMediaStream();
            mediaRecorderRef.current = null;
            setVoiceListening(false);
            setVoiceDraft('');
            setVoiceError('無法啟動麥克風錄音。請確認瀏覽器已允許 127.0.0.1:5173 使用麥克風；若 in-app Browser 仍然擋住，請用 Chrome 開啟同一個網址。');
        }
    };

    const totalLeads = contacts.length;
    const hotLeads = contacts.filter(c => c.lead_score >= 80).length;
    const avgScore = contacts.length ? Math.round(contacts.reduce((a, b) => a + b.lead_score, 0) / contacts.length) : 0;
    const gmailConnected = gmailStatus?.status === 'connected' && Boolean(gmailStatus?.has_refresh_token);
    const urgencyRank: Record<string, number> = { high: 0, medium: 1, low: 2 };
    const visibleNudges = nudges
        .slice()
        .sort((a, b) => (urgencyRank[a.urgency] ?? 3) - (urgencyRank[b.urgency] ?? 3))
        .filter((nudge, index, sortedNudges) => (
            sortedNudges.findIndex((item) => item.contact_id === nudge.contact_id) === index
        ));

    const urgencyStyles: Record<string, { bg: string; text: string; border: string; icon: string }> = {
        high: { bg: 'bg-red-500/10', text: 'text-red-400', border: 'border-red-500/30', icon: '🔴' },
        medium: { bg: 'bg-orange-500/10', text: 'text-orange-400', border: 'border-orange-500/30', icon: '🟡' },
        low: { bg: 'bg-blue-500/10', text: 'text-blue-400', border: 'border-blue-500/30', icon: '🔵' },
    };

    const actionIcons: Record<string, React.ReactNode> = {
        call: <Phone size={14} />,
        email: <Mail size={14} />,
        advance: <ArrowRight size={14} />,
        're-engage': <RefreshCw size={14} />,
    };

    const actionPresentation: Record<string, NudgeActionPresentation> = {
        call: {
            label: 'Call',
            message: (nudge) => (
                nudge.message.includes('999 days') || nudge.message.includes('no logged contact')
                    ? `${nudge.contact_name} 尚未記錄任何聯絡。建議先打一通 check-in call，之後把結果記錄到 CRM。`
                    : nudge.message
            ),
        },
        email: {
            label: 'Email',
            message: (nudge) => nudge.message,
        },
        advance: {
            label: 'Advance',
            message: (nudge) => nudge.message,
        },
        're-engage': {
            label: '重新聯繫',
            message: (nudge) => (
                nudge.message.includes('Re-engage')
                    ? `${nudge.contact_name} 進系統一段時間但還沒有互動紀錄。重新聯繫是指主動再聯絡一次；若已不適合追蹤，就封存。`
                    : nudge.message
            ),
        },
    };

    const segmentIcons: Record<string, React.ReactNode> = {
        iron_fan: <Flame size={18} className="text-orange-400" />,
        high_potential: <Zap size={18} className="text-yellow-400" />,
        sleeping: <Moon size={18} className="text-indigo-400" />,
        cold: <Snowflake size={18} className="text-cyan-400" />,
    };

    const segmentColors: Record<string, string> = {
        iron_fan: 'from-orange-500/20 to-red-500/10',
        high_potential: 'from-yellow-500/20 to-amber-500/10',
        sleeping: 'from-indigo-500/20 to-purple-500/10',
        cold: 'from-cyan-500/20 to-blue-500/10',
    };

    const refreshEmailReviews = async () => {
        try {
            const [status, drafts] = await Promise.all([
                crmService.getGmailStatus(),
                crmService.getPendingEmailDrafts(),
            ]);
            setGmailStatus(status);
            setPendingEmailDrafts(drafts.drafts);
        } catch (error) {
            console.error('Failed to refresh email reviews:', error);
        }
    };

    const handleConnectGmail = async () => {
        setEmailReviewFeedback('');
        try {
            const result = await crmService.startGmailOAuth();
            window.open(result.authorization_url, '_blank', 'noopener,noreferrer');
            setEmailReviewFeedback('Gmail authorization opened. Return here after Google confirms the connection.');
        } catch (error) {
            console.error('Failed to start Gmail OAuth:', error);
            setEmailReviewFeedback('Gmail OAuth is not configured yet. Add the OAuth env vars, then restart the backend.');
        }
    };

    const setDraftAction = (interactionId: number, value: string) => {
        setEmailReviewAction((current) => ({ ...current, [interactionId]: value }));
    };

    const handleCreateGmailDraft = async (draft: PendingEmailDraft) => {
        setEmailReviewFeedback('');
        setDraftAction(draft.interaction_id, 'creating');
        try {
            const result = await crmService.createGmailDraft(draft.interaction_id, {
                subject: draft.subject,
                body: draft.body,
            });
            setEmailReviewFeedback(result.message);
            await refreshEmailReviews();
        } catch (error) {
            console.error('Failed to create Gmail draft:', error);
            setEmailReviewFeedback('Could not create the Gmail draft. Check Gmail connection and recipient email.');
        } finally {
            setDraftAction(draft.interaction_id, '');
        }
    };

    const handleSendGmailDraft = async (draft: PendingEmailDraft) => {
        if (!draft.to_email) return;
        const from = gmailStatus?.account_email || 'connected Gmail';
        const reviewConfirmation = window.prompt(
            `Type 沒有問題 or OK to send this email now from ${from} to ${draft.to_email}.`
        );
        const normalizedConfirmation = reviewConfirmation?.trim();
        if (!normalizedConfirmation || !['沒有問題', '没问题', 'ok'].includes(normalizedConfirmation.toLowerCase())) {
            setEmailReviewFeedback('Send cancelled. Type 沒有問題 or OK only after reviewing the Gmail draft.');
            return;
        }

        setEmailReviewFeedback('');
        setDraftAction(draft.interaction_id, 'sending');
        try {
            const result = await crmService.sendGmailDraft(draft.interaction_id, {
                subject: draft.subject,
                body: draft.body,
                confirm_send: true,
                review_confirmation: normalizedConfirmation,
            });
            setEmailReviewFeedback(result.message);
            await refreshEmailReviews();
        } catch (error) {
            console.error('Failed to send Gmail draft:', error);
            setEmailReviewFeedback('Could not send through Gmail. Check connection, recipient email, and Google permissions.');
        } finally {
            setDraftAction(draft.interaction_id, '');
        }
    };

    if (loading) return <div className="p-8 text-center text-gray-400"><div className="spinner mx-auto mb-3"></div>Loading AI Dashboard...</div>;

    return (
        <div className="dashboard-page animate-fade-in p-2 sm:p-6">
            <header className="mb-6 sm:mb-8">
                <div className="flex justify-between items-start gap-3">
                    <div className="min-w-0">
                        <h1 className="text-xl sm:text-3xl font-bold mb-1 sm:mb-2">Welcome back, <span className="text-gradient">Kevin</span></h1>
                        <p className="text-gray-400 text-sm sm:text-base">Here is what's happening in your pipeline today.</p>
                    </div>
                    <button onClick={loadAll} className="btn btn-ghost text-xs sm:text-sm gap-2 flex items-center shrink-0">
                        <RefreshCw size={14} /> Refresh
                    </button>
                </div>
            </header>

            {/* Voice Memo Quick Input */}
            <div className="glass-panel mb-6 sm:mb-8">
                <div className="p-4 sm:p-5 border-b border-white/10 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                    <h2 className="text-base sm:text-lg font-bold flex items-center gap-2 mb-0">
                        <button
                            type="button"
                            onClick={voiceListening ? stopVoiceInput : startVoiceInput}
                            disabled={memoProcessing}
                            aria-label={voiceListening ? '停止錄音' : '開始錄音'}
                            aria-pressed={voiceListening}
                            title={!recorderSupported ? '瀏覽器不支援麥克風錄音' : voiceListening ? '停止錄音' : '開始錄音'}
                            className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full border transition-colors ${voiceListening ? 'border-red-500/40 bg-red-500/20 text-red-300' : 'border-green-500/30 bg-green-500/10 text-green-300 hover:bg-green-500/20'}`}
                        >
                            {voiceListening ? <Square size={16} /> : <Mic size={16} />}
                        </button>
                        語音備忘錄 Quick Entry
                    </h2>
                    <button
                        type="button"
                        onClick={voiceListening ? stopVoiceInput : startVoiceInput}
                        disabled={memoProcessing}
                        aria-pressed={voiceListening}
                        title={!recorderSupported ? '瀏覽器不支援麥克風錄音' : voiceListening ? '停止錄音' : '開始錄音'}
                        className={`btn text-xs sm:text-sm gap-2 shrink-0 ${voiceListening ? 'bg-red-500/20 text-red-200 border border-red-500/30 hover:bg-red-500/30' : 'btn-ghost'}`}
                    >
                        {voiceListening ? <Square size={14} /> : <Mic size={14} />}
                        {voiceListening ? 'Stop' : 'Record'}
                    </button>
                </div>
                <div className="p-4 sm:p-5">
                    <div className="flex flex-col sm:flex-row gap-3">
                        <textarea
                            value={memoText}
                            onChange={(e) => setMemoText(e.target.value)}
                            placeholder="貼上語音轉文字... 例如：王太太今天看了萬錦獨立屋，嫌廚房小但喜歡學區，預算1.5M"
                            className="flex-1 bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm resize-none outline-none focus:border-purple-500 transition-colors"
                            rows={2}
                        />
                        <button
                            onClick={async () => {
                                if (!memoText.trim()) return;
                                setMemoProcessing(true);
                                setMemoResult(null);
                                try {
                                    const result = await crmService.voiceMemo(memoText);
                                    setMemoResult(result);
                                    if (result.success) {
                                        setMemoText('');
                                        loadAll();
                                    }
                                } catch (e) {
                                    console.error('Voice memo failed:', e);
                                } finally {
                                    setMemoProcessing(false);
                                }
                            }}
                            disabled={memoProcessing || !memoText.trim()}
                            className="px-5 py-3 bg-gradient-to-r from-green-500 to-emerald-600 hover:from-green-400 hover:to-emerald-500 rounded-xl font-semibold text-sm transition-all disabled:opacity-50 flex items-center gap-2 shrink-0"
                        >
                            <Send size={14} />
                            {memoProcessing ? 'Processing...' : 'Analyze & Save'}
                        </button>
                    </div>
                    {(voiceListening || voiceDraft || voiceError || transcribingAudio) && (
                        <div className="mt-3 text-xs sm:text-sm">
                            {voiceListening && (
                                <p className="text-green-300">
                                    Recording {formatRecordingTime(recordingSeconds)}
                                    {voiceDraft && <span className="text-gray-300"> {voiceDraft}</span>}
                                </p>
                            )}
                            {transcribingAudio && <p className="text-yellow-300">Transcribing with local Whisper...</p>}
                            {voiceError && <p className="text-red-300">{voiceError}</p>}
                        </div>
                    )}
                    {recordingUrl && (
                        <div className="mt-4 rounded-xl border border-white/10 bg-white/5 p-3">
                            <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                                <audio controls src={recordingUrl} className="w-full sm:flex-1" />
                                <button type="button" onClick={clearRecording} className="btn btn-ghost text-xs shrink-0">
                                    Clear
                                </button>
                            </div>
                            <p className="mt-2 text-xs text-gray-400">
                                錄音格式: {recordingMimeType || 'audio'}。停止錄音後會先用本機 Whisper 轉文字；Analyze & Save 會分析文字框內容並存到 Contacts & Leads。
                            </p>
                        </div>
                    )}
                    {memoResult && (
                        <div className={`mt-4 p-4 rounded-xl border ${memoResult.success ? 'bg-green-500/10 border-green-500/20' : 'bg-red-500/10 border-red-500/20'}`}>
                            <p className="text-sm font-medium mb-2">{memoResult.message}</p>
                            {memoResult.extracted_data && (
                                <div className="text-xs text-gray-400 space-y-1">
                                    {(() => {
                                        const d = memoResult.extracted_data as VoiceMemoExtractedData; return (<>
                                            {Array.isArray(d.areas) && <p>📍 Areas: {d.areas.join(', ')}</p>}
                                            {d.budget && <p>💰 Budget: ${Number(d.budget).toLocaleString()}</p>}
                                            {Array.isArray(d.likes) && <p>👍 Likes: {d.likes.join(', ')}</p>}
                                            {Array.isArray(d.dislikes) && <p>👎 Dislikes: {d.dislikes.join(', ')}</p>}
                                        </>);
                                    })()}
                                </div>
                            )}
                            {memoResult.email_draft && (
                                <div className="mt-3 p-3 bg-white/5 rounded-lg">
                                    <p className="text-xs text-purple-400 font-medium mb-1">📧 {memoResult.email_draft.subject}</p>
                                    <p className="text-xs text-gray-400 whitespace-pre-line">{memoResult.email_draft.body.substring(0, 200)}...</p>
                                </div>
                            )}
                            {memoResult.success && memoResult.client_id && (
                                <div className="mt-3 flex flex-wrap gap-2">
                                    <Link
                                        to={`/contacts?contact_id=${memoResult.client_id}`}
                                        className="btn btn-ghost text-xs"
                                    >
                                        Open Contact
                                    </Link>
                                    <Link
                                        to={`/watchlists?contact_id=${memoResult.client_id}`}
                                        className="btn btn-ghost text-xs"
                                    >
                                        Open Watchlist
                                    </Link>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </div>

            {/* Gmail Review Queue */}
            <div className="glass-panel mb-6 sm:mb-8">
                <div className="p-4 sm:p-5 border-b border-white/10 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                    <div>
                        <h2 className="text-base sm:text-lg font-bold flex items-center gap-2 mb-1">
                            <Mail size={18} className="text-purple-300" /> Gmail Review Queue
                        </h2>
                        <p className="text-xs text-gray-400">
                            {gmailConnected
                                ? `Connected: ${gmailStatus?.account_email || 'Gmail'}`
                                : gmailStatus?.oauth_configured
                                    ? 'Gmail not connected'
                                    : 'Gmail OAuth not configured'}
                        </p>
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-500 bg-white/5 px-2 py-1 rounded-full">
                            {pendingEmailDrafts.length} pending
                        </span>
                        {!gmailConnected && (
                            <button type="button" onClick={handleConnectGmail} className="btn btn-ghost text-xs">
                                Connect Gmail
                            </button>
                        )}
                    </div>
                </div>
                <div className="p-4 sm:p-5 space-y-3">
                    {emailReviewFeedback && (
                        <div className="rounded-lg border border-purple-500/20 bg-purple-500/10 px-3 py-2 text-xs text-purple-200">
                            {emailReviewFeedback}
                        </div>
                    )}
                    {pendingEmailDrafts.length > 0 ? pendingEmailDrafts.map((draft) => {
                        const actionState = emailReviewAction[draft.interaction_id];
                        const canCreateDraft = gmailConnected && Boolean(draft.to_email) && draft.status !== 'gmail_draft_created';
                        const canSend = gmailConnected && Boolean(draft.to_email);

                        return (
                            <div key={draft.interaction_id} className="rounded-xl border border-white/10 bg-white/5 p-4">
                                <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-3">
                                    <div className="min-w-0">
                                        <div className="flex flex-wrap items-center gap-2 mb-2">
                                            <span className="font-semibold text-sm">{draft.contact_name}</span>
                                            <span className="text-xs text-gray-500">{draft.to_email || 'No email on contact'}</span>
                                            <span className="text-[11px] uppercase tracking-wide rounded-full border border-yellow-500/20 bg-yellow-500/10 px-2 py-0.5 text-yellow-200">
                                                {draft.status || 'pending_review'}
                                            </span>
                                        </div>
                                        <p className="text-sm font-medium text-gray-200 truncate">{draft.subject}</p>
                                        <p className="mt-1 text-xs text-gray-400 line-clamp-2">{draft.body}</p>
                                    </div>
                                    <div className="flex flex-wrap gap-2 shrink-0">
                                        <button
                                            type="button"
                                            onClick={() => handleCreateGmailDraft(draft)}
                                            disabled={!canCreateDraft || Boolean(actionState)}
                                            className="btn btn-ghost text-xs disabled:opacity-40"
                                            title={!draft.to_email ? 'Add an email address to the contact first.' : undefined}
                                        >
                                            {actionState === 'creating' ? 'Creating...' : draft.gmail_draft_id ? 'Draft Created' : 'Create Gmail Draft'}
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => handleSendGmailDraft(draft)}
                                            disabled={!canSend || Boolean(actionState)}
                                            className="btn text-xs bg-green-500/20 text-green-100 border border-green-500/30 hover:bg-green-500/30 disabled:opacity-40"
                                            title={!draft.to_email ? 'Add an email address to the contact first.' : undefined}
                                        >
                                            {actionState === 'sending' ? 'Sending...' : 'Send Now'}
                                        </button>
                                    </div>
                                </div>
                            </div>
                        );
                    }) : (
                        <div className="rounded-xl border border-dashed border-white/10 bg-black/20 p-6 text-center text-sm text-gray-500">
                            No pending email drafts.
                        </div>
                    )}
                </div>
            </div>

            {/* Metrics Row */}
            <div className="grid grid-cols-3 gap-3 sm:gap-6 mb-6 sm:mb-8">
                <div className="glass-card flex flex-col sm:flex-row items-center gap-2 sm:gap-4 text-center sm:text-left p-3 sm:p-6">
                    <div className="p-2 sm:p-3 bg-blue-500/20 rounded-xl text-blue-400">
                        <Users size={22} className="sm:w-7 sm:h-7" />
                    </div>
                    <div>
                        <p className="text-[10px] sm:text-sm text-gray-400 font-medium">Total</p>
                        <h3 className="text-xl sm:text-2xl font-bold">{totalLeads}</h3>
                    </div>
                </div>

                <div className="glass-card flex flex-col sm:flex-row items-center gap-2 sm:gap-4 text-center sm:text-left p-3 sm:p-6 border-l-2 sm:border-l-4 border-l-red-500">
                    <div className="p-2 sm:p-3 bg-red-500/20 rounded-xl text-red-500">
                        <Target size={22} className="sm:w-7 sm:h-7" />
                    </div>
                    <div>
                        <p className="text-[10px] sm:text-sm text-gray-400 font-medium">Hot Leads</p>
                        <h3 className="text-xl sm:text-2xl font-bold">{hotLeads}</h3>
                    </div>
                </div>

                <div className="glass-card flex flex-col sm:flex-row items-center gap-2 sm:gap-4 text-center sm:text-left p-3 sm:p-6 border-l-2 sm:border-l-4 border-l-purple-500">
                    <div className="p-2 sm:p-3 bg-purple-500/20 rounded-xl text-purple-400">
                        <TrendingUp size={22} className="sm:w-7 sm:h-7" />
                    </div>
                    <div>
                        <p className="text-[10px] sm:text-sm text-gray-400 font-medium">Avg Score</p>
                        <h3 className="text-xl sm:text-2xl font-bold">{avgScore}</h3>
                    </div>
                </div>
            </div>

            {/* Two-column layout: Nudges + Segments */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6 mb-6 sm:mb-8">

                {/* AI Smart Nudges */}
                <div className="glass-panel">
                    <div className="p-5 border-b border-white/10 flex items-center justify-between">
                        <h2 className="text-lg font-bold flex items-center gap-2">
                            <AlertTriangle size={18} className="text-yellow-400" /> AI Smart Nudges
                        </h2>
                        <span className="text-xs text-gray-500 bg-white/5 px-2 py-1 rounded-full">
                            {visibleNudges.length} contacts
                        </span>
                    </div>
                    <div className="divide-y divide-white/5 max-h-[400px] overflow-y-auto">
                        {visibleNudges.length > 0 ? visibleNudges.map((nudge) => {
                            const style = urgencyStyles[nudge.urgency] || urgencyStyles.low;
                            const action = actionPresentation[nudge.action] || {
                                label: nudge.action,
                                message: () => nudge.message,
                            };
                            return (
                                <div key={`${nudge.contact_id}-${nudge.action}`} className={`p-4 hover:bg-white/5 transition-colors ${style.bg}`}>
                                    <div className="flex items-start gap-3">
                                        <span className="text-lg mt-0.5">{style.icon}</span>
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2 mb-1">
                                                <span className="font-semibold text-sm">{nudge.contact_name}</span>
                                                {nudge.company && <span className="text-xs text-gray-500">• {nudge.company}</span>}
                                            </div>
                                            <p className="text-sm text-gray-300">{action.message(nudge)}</p>
                                        </div>
                                        <div className={`flex items-center gap-1 text-xs px-2 py-1 rounded-full border ${style.border} ${style.text}`}>
                                            {actionIcons[nudge.action]}
                                            <span>{action.label}</span>
                                        </div>
                                    </div>
                                </div>
                            );
                        }) : (
                            <div className="p-8 text-center text-gray-500">
                                ✅ No urgent actions needed. Pipeline looks great!
                            </div>
                        )}
                    </div>
                </div>

                {/* Customer Segments */}
                <div className="glass-panel">
                    <div className="p-5 border-b border-white/10">
                        <h2 className="text-lg font-bold flex items-center gap-2">
                            🏷️ Customer Segments
                        </h2>
                    </div>
                    <div className="p-5 space-y-4">
                        {segments.length > 0 ? segments.map((seg) => {
                            const total = contacts.length || 1;
                            const pct = Math.round(seg.count / total * 100);
                            const gradient = segmentColors[seg.key] || 'from-gray-500/20 to-gray-500/10';
                            return (
                                <div key={seg.key} className={`rounded-xl p-4 bg-gradient-to-r ${gradient} border border-white/5`}>
                                    <div className="flex items-center justify-between mb-2">
                                        <div className="flex items-center gap-2">
                                            {segmentIcons[seg.key]}
                                            <span className="font-semibold">{seg.label}</span>
                                        </div>
                                        <span className="text-lg font-bold">{seg.count}</span>
                                    </div>
                                    <div className="w-full bg-white/10 rounded-full h-2">
                                        <div
                                            className="h-2 rounded-full bg-white/30 transition-all"
                                            style={{ width: `${pct}%` }}
                                        ></div>
                                    </div>
                                    <p className="text-xs text-gray-400 mt-1">{pct}% of pipeline</p>
                                </div>
                            );
                        }) : (
                            <div className="p-8 text-center text-gray-500">
                                No contacts yet. Add some to see segmentation.
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {/* Pipeline Insights */}
            {insights && (
                <div className="glass-panel mb-8">
                    <div className="p-5 border-b border-white/10">
                        <h2 className="text-lg font-bold flex items-center gap-2">
                            📊 Pipeline Insights
                        </h2>
                    </div>
                    <div className="p-5">
                        {/* Conversion summary */}
                        <div className="bg-gradient-to-r from-purple-500/10 to-indigo-500/10 border border-purple-500/20 rounded-xl p-4 mb-5">
                            <p className="text-sm font-medium text-purple-300">{insights.conversion_summary}</p>
                        </div>

                        {/* Stage breakdown bars */}
                        {insights.stage_breakdown.length > 0 && (
                            <div className="space-y-3 mb-5">
                                {insights.stage_breakdown.map((stage) => (
                                    <div key={stage.name} className="flex items-center gap-3">
                                        <span className="text-sm font-medium text-gray-300 w-28 truncate">{stage.name}</span>
                                        <div className="flex-1 bg-white/10 rounded-full h-3">
                                            <div
                                                className="h-3 rounded-full bg-gradient-to-r from-purple-500 to-indigo-500 transition-all"
                                                style={{ width: `${stage.percentage}%` }}
                                            ></div>
                                        </div>
                                        <span className="text-sm font-bold w-12 text-right">{stage.count}</span>
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* Bottleneck warning */}
                        {insights.bottleneck && (
                            <div className="bg-orange-500/10 border border-orange-500/20 rounded-lg p-3 mb-4 flex items-center gap-2">
                                <AlertTriangle size={16} className="text-orange-400 shrink-0" />
                                <p className="text-sm text-orange-300">{insights.bottleneck}</p>
                            </div>
                        )}

                        {/* AI Recommendations */}
                        <div>
                            <h3 className="text-sm font-semibold text-gray-400 mb-2">💡 AI Recommendations</h3>
                            <ul className="space-y-2">
                                {insights.recommendations.map((rec, i) => (
                                    <li key={i} className="text-sm text-gray-300 flex items-start gap-2">
                                        <span className="text-purple-400 mt-0.5">→</span>
                                        {rec}
                                    </li>
                                ))}
                            </ul>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default Dashboard;
