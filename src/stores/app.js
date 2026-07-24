import { acceptHMRUpdate, defineStore } from 'pinia'
import { api } from '../services/api'
const preferredTheme=()=>localStorage.getItem('theme')||(window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light')
export const useAppStore=defineStore('app',{state:()=>({dashboard:null,loading:false,error:null,syncError:null,theme:preferredTheme()}),actions:{async load(force=false){if(this.loading||(this.dashboard&&!force))return;this.loading=true;if(!this.dashboard)this.error=null;try{this.dashboard=await api.dashboard(force);this.error=null;this.syncError=null}catch(e){if(this.dashboard)this.syncError=e.message;else this.error=e.message}finally{this.loading=false}},applyTheme(){const root=document.documentElement;root.classList.toggle('dark',this.theme==='dark');root.classList.toggle('light',this.theme==='light')},toggleTheme(){this.theme=this.theme==='dark'?'light':'dark';localStorage.setItem('theme',this.theme);this.applyTheme()}}})

if (import.meta.hot) import.meta.hot.accept(acceptHMRUpdate(useAppStore, import.meta.hot))
