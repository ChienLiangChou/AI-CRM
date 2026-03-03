import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

const api = axios.create({
    baseURL: API_BASE_URL,
});

export interface Contact {
    id: number;
    name: string;
    email?: string;
    phone?: string;
    company?: string;
    notes?: string;
    lead_score: number;
    stage_id?: number;
}

export interface SmartSearchResult {
    query: string;
    interpreted_intent: string;
    results: Contact[];
}

export interface EmailDraftResponse {
    subject: string;
    body: string;
}

export interface EnrichProfileResponse {
    summary: string;
    updated_notes: string;
}

export interface ScoutResponse {
    message: string;
    new_contacts: Contact[];
}

export const crmService = {
    getContacts: async () => {
        const response = await api.get<Contact[]>('/contacts');
        return response.data;
    },

    createContact: async (data: Partial<Contact>) => {
        const response = await api.post<Contact>('/contacts', data);
        return response.data;
    },

    smartSearch: async (query: string) => {
        const response = await api.get<SmartSearchResult>('/smart-search', { params: { q: query } });
        return response.data;
    },

    draftEmail: async (contactId: number) => {
        const response = await api.post<EmailDraftResponse>(`/contacts/${contactId}/draft-email`);
        return response.data;
    },

    enrichProfile: async (contactId: number) => {
        const response = await api.post<EnrichProfileResponse>(`/contacts/${contactId}/enrich`);
        return response.data;
    },

    scoutLeads: async (query: string) => {
        const response = await api.post<ScoutResponse>('/prospector/scout', { query });
        return response.data;
    }
};
