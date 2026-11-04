"""Verify a separately staged, CI-tested coherent Windows client. No connection."""
import ctypes,hashlib,json,os,re,sys
from pathlib import Path,PurePosixPath
class ClientStop(RuntimeError):pass
def require(value,code):
 if not value:raise ClientStop(code)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def inside(root,relative):
 require(isinstance(relative,str) and bool(relative),'CLIENT_MANIFEST_PATH_INVALID')
 value=PurePosixPath(relative)
 require( not value.is_absolute() and '..' not in value.parts and '\\' not in relative and ':' not in relative and str(value)==relative,'CLIENT_MANIFEST_PATH_INVALID')
 path=root.joinpath(*value.parts)
 require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root.resolve()) and all(not part.is_symlink() and not (hasattr(part,'is_junction') and part.is_junction()) for part in (path,*path.parents) if part!=root.parent),'CLIENT_FILE_UNSAFE')
 return path

def validate_manifest(root,profile):
 require(root.is_dir() and all(not p.is_symlink() and not (hasattr(p,'is_junction') and p.is_junction()) for p in (root,*root.parents)),'CLIENT_SIDECAR_MISSING')
 require(profile.get('package_version')=='2.9.12','CLIENT_PACKAGE_VERSION_NOT_APPROVED')
 require(profile.get('libpq_compile_version')==180006 and profile.get('libpq_runtime_version')==180006,'CLIENT_LIBPQ18_6_PROOF_REQUIRED')
 files=profile.get('files');require(isinstance(files,dict) and files,'CLIENT_FILE_MANIFEST_REQUIRED')
 require(len({n.casefold() for n in files if isinstance(n,str)})==len(files),'CLIENT_FILE_ALIAS_COLLISION')
 require(all(isinstance(v,str) and re.fullmatch('[a-f0-9]{64}',v) for v in files.values()),'CLIENT_FILE_HASH_INVALID')
 actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
 require(actual==set(files),'CLIENT_FILE_SET_CHANGED')
 for name,expected in files.items():require(sha(inside(root,name))==expected,'CLIENT_FILE_HASH_MISMATCH')
 extension=profile.get('extension_relative_path');require(extension in files and extension.startswith('psycopg2/') and extension.endswith('.pyd'),'CLIENT_EXTENSION_PROOF_REQUIRED')
 dlls=profile.get('loaded_dlls');require(isinstance(dlls,dict) and dlls,'CLIENT_DLL_PROOF_REQUIRED')
 for name,entry in dlls.items():
  require(isinstance(name,str) and '/' not in name and '\\' not in name and name.lower().endswith('.dll'),'CLIENT_DLL_NAME_INVALID')
  require(isinstance(entry,dict) and entry.get('relative_path') in files,'CLIENT_DLL_FILE_REQUIRED')
  require(PurePosixPath(entry['relative_path']).name==name and files[entry['relative_path']]==entry.get('sha256'),'CLIENT_DLL_HASH_PROOF_MISMATCH')
 require(any('libpq' in n.lower() for n in dlls) and any('libssl' in n.lower() for n in dlls) and any('libcrypto' in n.lower() for n in dlls),'CLIENT_COHERENT_TLS_BUNDLE_REQUIRED')
 return files

def loaded_module_path(name):
 require(sys.platform=='win32','WINDOWS_CLIENT_REQUIRED')
 kernel=ctypes.WinDLL('kernel32',use_last_error=True)
 kernel.GetModuleHandleW.argtypes=[ctypes.c_wchar_p];kernel.GetModuleHandleW.restype=ctypes.c_void_p
 kernel.GetModuleFileNameW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint];kernel.GetModuleFileNameW.restype=ctypes.c_uint
 handle=kernel.GetModuleHandleW(name);require(bool(handle),'CLIENT_DLL_NOT_LOADED')
 output=ctypes.create_unicode_buffer(32768);length=kernel.GetModuleFileNameW(handle,output,len(output));require(0<length<len(output),'CLIENT_DLL_PATH_UNAVAILABLE')
 return Path(output.value).resolve()

def loaded_file_version(path):
 require(sys.platform=='win32','WINDOWS_CLIENT_REQUIRED')
 version=ctypes.WinDLL('version',use_last_error=True)
 version.GetFileVersionInfoSizeW.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_uint)];version.GetFileVersionInfoSizeW.restype=ctypes.c_uint
 version.GetFileVersionInfoW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p];version.GetFileVersionInfoW.restype=ctypes.c_int
 version.VerQueryValueW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(ctypes.c_uint)];version.VerQueryValueW.restype=ctypes.c_int
 unused=ctypes.c_uint(0);size=version.GetFileVersionInfoSizeW(str(path),ctypes.byref(unused))
 if not size:return None
 buffer=ctypes.create_string_buffer(size)
 require(bool(version.GetFileVersionInfoW(str(path),0,size,buffer)),'CLIENT_DLL_VERSION_READ_FAILED')
 pointer=ctypes.c_void_p();length=ctypes.c_uint()
 require(bool(version.VerQueryValueW(buffer,'\\',ctypes.byref(pointer),ctypes.byref(length))) and length.value>=52,'CLIENT_DLL_VERSION_FORMAT_INVALID')
 data=ctypes.cast(pointer,ctypes.POINTER(ctypes.c_uint*13)).contents
 require(data[0]==0xfeef04bd,'CLIENT_DLL_VERSION_SIGNATURE_INVALID')
 return '.'.join(str(n) for n in (data[2]>>16,data[2]&65535,data[3]>>16,data[3]&65535))

def validate_loaded_client(root,profile):
 require(sys.platform=='win32' and sys.version_info[:2]==(3,12),'WINDOWS_PYTHON312_CLIENT_REQUIRED')
 validate_manifest(root,profile)
 import psycopg2
 from psycopg2 import extensions,_psycopg
 require(psycopg2.__version__.split()[0]=='2.9.12','LOADED_CLIENT_PACKAGE_MISMATCH')
 require(int(psycopg2.__libpq_version__)==180006 and int(extensions.libpq_version())==180006,'LOADED_CLIENT_LIBPQ_MISMATCH')
 require(Path(_psycopg.__file__).resolve()==inside(root,profile['extension_relative_path']).resolve(),'LOADED_CLIENT_EXTENSION_PATH_MISMATCH')
 loaded=[]
 for name,entry in profile['loaded_dlls'].items():
  actual=loaded_module_path(name);expected=inside(root,entry['relative_path']).resolve()
  require(actual==expected and sha(actual)==entry['sha256'],'LOADED_CLIENT_DLL_MISMATCH')
  version=loaded_file_version(actual)
  require('file_version' in entry and version==entry['file_version'],'LOADED_CLIENT_DLL_VERSION_MISMATCH')
  loaded.append({'name':name,'absolute_path':str(actual),'sha256':entry['sha256'],'file_version':version})
 crypto_names=[n for n in profile['loaded_dlls'] if 'libcrypto' in n.lower()]
 require(len(crypto_names)==1,'CLIENT_CRYPTO_MODULE_AMBIGUOUS')
 crypto=ctypes.CDLL(str(loaded_module_path(crypto_names[0])))
 crypto.OpenSSL_version_num.argtypes=[];crypto.OpenSSL_version_num.restype=ctypes.c_ulong
 crypto.OpenSSL_version.argtypes=[ctypes.c_int];crypto.OpenSSL_version.restype=ctypes.c_char_p
 openssl={'number':int(crypto.OpenSSL_version_num()),'text':crypto.OpenSSL_version(0).decode('ascii')}
 require(openssl==profile.get('openssl_version'),'LOADED_CLIENT_OPENSSL_VERSION_MISMATCH')
 require(extensions.get_wait_callback() is None,'CUSTOM_CLIENT_WAIT_CALLBACK_BLOCKED')
 return {'package_version':'2.9.12','libpq_compile_version':180006,'libpq_runtime_version':180006,'loaded_extension_and_dll_hashes_match':True,'custom_wait_callback':False,'loaded_dlls':loaded,'openssl_version':openssl}

def policy_profile(root,policy):
 require(policy.get('windows_client_acceptance_passed') is True,'WINDOWS_CLIENT_CI_SEAL_REQUIRED')
 profile=policy.get('windows_client_acceptance');require(isinstance(profile,dict),'WINDOWS_CLIENT_PROOF_MISSING')
 require(profile.get('actual_windows') is True,'ACTUAL_WINDOWS_CLIENT_PROOF_REQUIRED')
 require(profile.get('candidate_commit')==policy.get('tested_commit') and bool(re.fullmatch('[a-f0-9]{40}',str(profile.get('candidate_commit','')))),'CLIENT_COMMIT_PROOF_MISMATCH')
 require(bool(re.fullmatch('[a-f0-9]{64}',str(profile.get('wheel_sha256','')))) and profile.get('source_sdist_sha256')=='1dedb1c7a1d8552c4a6044c6b1c41a52e6a8e2d144af83eccac758076b1b7c15','CLIENT_SUPPLY_CHAIN_PROOF_REQUIRED')
 require(profile.get('pg_archive_sha256')=='e2246ba91d22345bc3d017586c09ede52d9df180b1eeb480f050445f1cad84e2','CLIENT_PG18_6_SOURCE_PROOF_REQUIRED')
 require(profile.get('runner_sha256')==sha(root/'worlex_restore.py'),'CLIENT_PROOF_RUNNER_MISMATCH')
 require(profile.get('guard_sha256')==sha(Path(__file__)),'CLIENT_PROOF_GUARD_MISMATCH')
 summary=profile.get('acceptance_summary',{})
 require(summary.get('postgres_required') is True and summary.get('run',0)>=50 and summary.get('run')==summary.get('expected') and summary.get('errors')==summary.get('failures')==summary.get('skipped')==0,'FULL_WINDOWS_POSTGRES_ACCEPTANCE_REQUIRED')
 tls=profile.get('tls_acceptance',{})
 require(all(tls.get(k) is True for k in ('verify_full_used','wrong_root_rejected','wrong_hostname_rejected')),'WINDOWS_CLIENT_TLS_PROOF_REQUIRED')
 full=profile.get('full_table_acceptance',{})
 require(full.get('source_rows')==4100 and full.get('populated_tables')==37 and full.get('synthetic_only') is True,'WINDOWS_CLIENT_FULL_TABLE_PROOF_REQUIRED')
 require(all(full.get(k) is True for k in ('imported_values_and_blobs_match','preserved_rows_match','owner_bindings_quarantined')),'WINDOWS_CLIENT_VALUE_PRESERVATION_PROOF_REQUIRED')
 disconnect=profile.get('disconnect_acceptance',{})
 before=disconnect.get('before_commit',{});after=disconnect.get('after_commit',{})
 for item in (before,after):
  require(item.get('synthetic_only') is True and item.get('source_rows')==4100 and item.get('populated_tables')==37,'WINDOWS_CLIENT_DISCONNECT_SCOPE_REQUIRED')
 require(all(before.get(k) is True for k in ('actual_connection_closed_before_commit','all_imports_absent','preserved_rows_match','sequences_unchanged','fresh_readonly_verification_rejects_absent_restore')) and before.get('restore_retried') is False,'WINDOWS_CLIENT_ROLLBACK_PROOF_REQUIRED')
 require(all(after.get(k) is True for k in ('real_commit_then_client_error','fresh_readonly_verification_matches','preserved_rows_match','replay_guard_rejected_before_insert','sequences_unchanged_by_replay')) and after.get('network_packet_loss_reproduced') is False,'WINDOWS_CLIENT_RECONCILIATION_PROOF_REQUIRED')
 return profile

def enforce(root,policy):
 profile=policy_profile(root,policy)
 client_root=root/'client-sidecar'
 require(client_root.is_dir() and all(not p.is_symlink() and not (hasattr(p,'is_junction') and p.is_junction()) for p in (client_root,*client_root.parents)),'CLIENT_SIDECAR_MISSING')
 return validate_loaded_client(client_root,profile)
