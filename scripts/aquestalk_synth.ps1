# aquestalk_synth.ps1 - ゆっくり音声合成 via Win32Service reflection (32-bit PS)
# 呼び出し方:
#   C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe -ExecutionPolicy Bypass
#     -File aquestalk_synth.ps1 -Character reimu -TextFile input.txt -Output out.wav

param(
    [string]$Character = "reimu",
    [string]$TextFile  = "",
    [string]$Text      = "",
    [string]$Output    = "output.wav",
    [int]$Speed        = 100
)

$ErrorActionPreference = "Stop"

$AQ_BASE = "C:\Users\user\AppData\Local\Programs\YMM4\Resources\AquesTalk"
$SVC_EXE = "C:\Users\user\AppData\Local\Programs\YMM4\Resources\bin\YukkuriMovieMaker.Win32Service.exe"

# エンジン設定: aq1=AquesTalk1（霊夢/魔理沙の正式声）, aq2=AquesTalk2
$VOICE_CONFIG = @{
    "reimu"  = @{engine="aq1"; dll_dir="f1"}   # 霊夢: AquesTalk1 女性1（正式）
    "marisa" = @{engine="aq1"; dll_dir="f2"}   # 魔理沙: AquesTalk1 女性2（正式）
    # AquesTalk2 フォールバック（サブキャラ用）
    "f1b"    = @{engine="aq2"; phont="aq_f1b"}
    "f3a"    = @{engine="aq2"; phont="aq_f3a"}
    "m3"     = @{engine="aq2"; phont="aq_m3"}
    "momo1"  = @{engine="aq2"; phont="aq_momo1"}
}

$config = $VOICE_CONFIG[$Character.ToLower()]
if (-not $config) { $config = @{engine="aq1"; dll_dir="f1"} }

# Read text
if ($TextFile -ne "" -and (Test-Path $TextFile)) {
    $inputText = [System.IO.File]::ReadAllText($TextFile, [System.Text.Encoding]::UTF8).Trim()
} else {
    $inputText = $Text.Trim()
}
if ($inputText -eq "") { Write-Host "ERROR: empty text"; exit 1 }

# Load Win32Service assembly (32-bit)
$asm = [System.Reflection.Assembly]::LoadFile($SVC_EXE)

# Normalize text using AquesTalkHatsuonNormalizer
$normType = $asm.GetType('YukkuriMovieMaker.Win32Service.AquesTalkHatsuonNormalizer')
$normMethod = $normType.GetMethod('Normalize',
    [System.Reflection.BindingFlags]::Public -bor
    [System.Reflection.BindingFlags]::Static -bor
    [System.Reflection.BindingFlags]::Instance)

$normObj = $null
$normCtors = $normType.GetConstructors(
    [System.Reflection.BindingFlags]::Public -bor [System.Reflection.BindingFlags]::NonPublic -bor [System.Reflection.BindingFlags]::Instance
)
if ($normCtors.Count -gt 0 -and $normCtors[0].GetParameters().Count -eq 0) {
    $normObj = $normCtors[0].Invoke(@())
} elseif (-not ($normMethod.IsStatic)) {
    $normObj = [System.Runtime.Serialization.FormatterServices]::GetUninitializedObject($normType)
}

try {
    if ($normMethod.IsStatic) {
        $normalizedText = $normMethod.Invoke($null, @($inputText))
    } else {
        $normalizedText = $normMethod.Invoke($normObj, @($inputText))
    }
    if ($normalizedText -and $normalizedText -ne "") {
        $inputText = $normalizedText
    }
} catch {
    # normalization failed, use original text
}

# 出力ディレクトリを作成
$od = [System.IO.Path]::GetDirectoryName([System.IO.Path]::GetFullPath($Output))
if ($od -ne "" -and -not (Test-Path $od)) {
    New-Item -ItemType Directory -Path $od -Force | Out-Null
}

# AquesTalk1 または AquesTalk2 で合成
if ($config.engine -eq "aq1") {
    # AquesTalk1（霊夢=女性1/f1、魔理沙=女性2/f2）
    $aq1DllPath = "$AQ_BASE\$($config.dll_dir)\AquesTalk.dll"
    $t    = $asm.GetType('YukkuriMovieMaker.Win32Service.AquesTalk1')
    $ctor = $t.GetConstructors(
        [System.Reflection.BindingFlags]::NonPublic -bor
        [System.Reflection.BindingFlags]::Public -bor
        [System.Reflection.BindingFlags]::Instance
    )[0]
    $obj  = $ctor.Invoke(@($aq1DllPath))
    # GetMethod with explicit types to resolve overload ambiguity (String, Int32, String)
    $meth = $t.GetMethod('CreateVoice', [System.Type[]]@([string], [int], [string]))
    $errMsg = $meth.Invoke($obj, @($inputText, [int]$Speed, $Output))
} else {
    # AquesTalk2（サブキャラ用）
    $AQ2_DIR    = "$AQ_BASE\aq2"
    $DLL_PATH   = "$AQ2_DIR\AquesTalk2.dll"
    $PHONT_PATH = "$AQ2_DIR\phont\$($config.phont).phont"
    $t    = $asm.GetType('YukkuriMovieMaker.Win32Service.AquesTalk2')
    $ctor = $t.GetConstructors(
        [System.Reflection.BindingFlags]::NonPublic -bor
        [System.Reflection.BindingFlags]::Public -bor
        [System.Reflection.BindingFlags]::Instance
    )[0]
    $obj  = $ctor.Invoke(@($DLL_PATH, $PHONT_PATH))
    $meth = $t.GetMethod('CreateVoice')
    $errMsg = $meth.Invoke($obj, @($DLL_PATH, $PHONT_PATH, $inputText, [int]$Speed, $Output))
}

if ($errMsg -ne "" -and $errMsg -ne $null) {
    Write-Host "SYNTH_ERROR: $errMsg"
    exit 1
}

if (-not (Test-Path $Output)) {
    Write-Host "ERROR: output file not created"
    exit 1
}

$sz = (Get-Item $Output).Length
Write-Host "OK $sz"
