import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export class FileSearchStack extends cdk.Stack {
    constructor(scope: Construct, id: string, props?: cdk.StackProps) {
        super(scope, id, props);

        // ----------------------------------------
        // IAM User: ローカルMCPサーバーからBedrockを叩くためのユーザー
        // ----------------------------------------
        const bedrockUser = new iam.User(this, 'FileSearchBedrockUser', {
            userName: 'file-search-bedrock-user',
        });

        // ----------------------------------------
        // IAM Policy: Bedrock モデル呼び出し権限
        // ----------------------------------------
        const bedrockPolicy = new iam.ManagedPolicy(this, 'FileSearchBedrockPolicy', {
            managedPolicyName: 'FileSearchBedrockPolicy',
            statements: [
                
                // Embedding: Titan Embed（foundation-model ARN）モデルへのアクセスを許可
                new iam.PolicyStatement({
                    sid: 'BedrockEmbedding',
                    effect: iam.Effect.ALLOW,
                    actions: ['bedrock:InvokeModel'],
                    resources: [
                        'arn:aws:bedrock:ap-northeast-1::foundation-model/amazon.titan-embed-text-v2:0',
                    ],
                }),

                // LLM: JP推論プロファイル経由でClaude Sonnet 4.6を呼び出す
                // ストリーミング応答も許可する（現在未実装）
                new iam.PolicyStatement({
                    sid: 'BedrockInferenceProfile',
                    effect: iam.Effect.ALLOW,
                    actions: [
                        'bedrock:InvokeModel',
                        'bedrock:InvokeModelWithResponseStream',
                    ],
                    resources: [
                        // JP推論プロファイル（アカウントID付きの完全ARN 東京と大阪どちらにルーティングされても大丈夫なように）
                        'arn:aws:bedrock:ap-northeast-1:716287580111:inference-profile/jp.anthropic.claude-sonnet-4-6',
                        // 推論プロファイルが内部でルーティングする先のモデル（東京 or 大阪）
                        'arn:aws:bedrock:ap-northeast-1::foundation-model/anthropic.claude-sonnet-4-6',
                        'arn:aws:bedrock:ap-northeast-3::foundation-model/anthropic.claude-sonnet-4-6',
                    ],
                }),

                // Bedrock全般: モデルのリスト取得や推論プロファイルの情報取得など、運用に必要な最低限の権限
                // LlamaIndexがBedrockに接続する際、利用可能なモデルを確認するためにListFoundationModelsを呼び出すため、これらの権限が必要
                new iam.PolicyStatement({
                    sid: 'BedrockGeneral',
                    effect: iam.Effect.ALLOW,
                    actions: [
                        'bedrock:ListFoundationModels',     // Bedrockで使えるモデルの一覧を取得
                        'bedrock:ListInferenceProfiles',    // Bedrockで使える推論プロファイルの一覧を取得
                        'bedrock:GetInferenceProfile',      // 特定の推論プロファイルの詳細情報（どのモデル・どのリージョンにルーティングするか）を取得
                    ],
                    resources: ['*'],
                }),

                // AWS Marketplace: 推論プロファイル使用に必要な権限
                new iam.PolicyStatement({
                    sid: 'MarketplaceSubscription',
                    effect: iam.Effect.ALLOW,
                    actions: [
                        'aws-marketplace:ViewSubscriptions', // 現在のサブスクリプション状態を確認する権限
                        'aws-marketplace:Subscribe',         // 推論プロファイルの利用開始時に必要なサブスクライブの権限（初回のみ必要）
                        'aws-marketplace:Unsubscribe',       // サブスクリプションを解除する権限
                    ],
                    resources: ['*'],
                }),
            ],
        });
        
        // IAM UserにIAM Policyをアタッチ
        bedrockUser.addManagedPolicy(bedrockPolicy);

        // ----------------------------------------
        // アクセスキーの生成
        // ----------------------------------------
        const accessKey = new iam.CfnAccessKey(this, 'FileSearchAccessKey', {
            userName: bedrockUser.userName,
        });

        // ----------------------------------------
        // Outputs: デプロイ後にターミナルに表示される
        // ----------------------------------------
        new cdk.CfnOutput(this, 'BedrockUserName', {
            value: bedrockUser.userName,
            description: 'IAM User for File Search Agent',
        });

        new cdk.CfnOutput(this, 'AccessKeyId', {
            value: accessKey.ref,
            description: 'AWS Access Key ID - set to .env',
        });

        new cdk.CfnOutput(this, 'SecretAccessKey', {
            value: accessKey.attrSecretAccessKey,
            description: 'AWS Secret Access Key - set to .env',
        });
    }
}