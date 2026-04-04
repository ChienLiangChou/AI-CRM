import axios from 'axios';

type ValidationDetailItem = {
    loc?: unknown;
    msg?: unknown;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value !== null;

const normalizeString = (value: unknown): string | null => {
    if (typeof value !== 'string') {
        return null;
    }

    const trimmed = value.trim();
    return trimmed ? trimmed : null;
};

const formatValidationDetail = (detail: unknown): string | null => {
    if (!Array.isArray(detail)) {
        return null;
    }

    const messages = detail
        .map((item) => {
            if (!isRecord(item)) {
                return null;
            }

            const loc = Array.isArray((item as ValidationDetailItem).loc)
                ? ((item as ValidationDetailItem).loc as unknown[])
                      .map((part) => normalizeString(part) ?? String(part))
                      .join(' -> ')
                : null;
            const msg = normalizeString((item as ValidationDetailItem).msg);
            if (!msg) {
                return null;
            }

            return loc ? `${loc}: ${msg}` : msg;
        })
        .filter((item): item is string => Boolean(item));

    return messages.length > 0 ? messages.join(' | ') : null;
};

const extractDetailMessage = (data: unknown): string | null => {
    const directText = normalizeString(data);
    if (directText) {
        return directText;
    }

    if (!isRecord(data)) {
        return null;
    }

    const detail = data.detail;
    return normalizeString(detail) ?? formatValidationDetail(detail);
};

export const getApiErrorMessage = (error: unknown, fallback: string): string => {
    if (!axios.isAxiosError(error)) {
        return error instanceof Error && error.message.trim() ? error.message : fallback;
    }

    if (error.response) {
        const status = error.response.status;
        const detailMessage = extractDetailMessage(error.response.data);

        if (status === 404) {
            return detailMessage
                ? `Route not found (404): ${detailMessage}`
                : 'Route not found (404).';
        }

        if (status === 422) {
            return detailMessage
                ? `Validation failed (422): ${detailMessage}`
                : 'Validation failed (422).';
        }

        if (status >= 500) {
            return detailMessage
                ? `Internal server error (${status}): ${detailMessage}`
                : `Internal server error (${status}).`;
        }

        if (detailMessage) {
            return detailMessage;
        }

        return `Request failed (${status}).`;
    }

    const cause = (error as { cause?: unknown }).cause;
    const causeCode =
        isRecord(cause) && typeof cause.code === 'string'
            ? cause.code
            : null;

    if (error.code === 'ECONNREFUSED' || causeCode === 'ECONNREFUSED') {
        return 'Connection refused: backend is not accepting requests at the configured API URL.';
    }

    if (error.code === 'ERR_NETWORK') {
        return 'Network error: backend unreachable or blocked before a response (connection refused or CORS).';
    }

    return normalizeString(error.message) ?? fallback;
};
